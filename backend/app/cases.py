"""Case logic shared by the voice tools, the webhook, the dashboard and the simulator."""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from . import db, dedupe, elevenlabs, gemini, grounding, memory
from .areas import area_mentioned, nearest_area
from .geocode import geocode
from .realtime import hub
from .scoring import VERIFY_PEOPLE, base_score, has_injury, label_for, normalize_water, wait_bonus

log = logging.getLogger("lifeline.cases")

DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
FAKE_PHONE_PREFIX = "+1555"

_background: set[asyncio.Task] = set()
_seen_conversations: set[str] = set()
# ElevenLabs fires tools in parallel (flag_critical + submit at the same instant). Without this,
# both see "no case yet" and a new caller gets two cases. One process, so an in-memory lock is enough.
_case_lock = asyncio.Lock()


def spawn(coro) -> None:
    """Run work after the response is sent, keeping a reference so it isn't garbage-collected."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


# ---------- small helpers ----------

def clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "unknown", "n/a", "na", "empty", "no"}:
        return None
    return text


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        n = int(float(str(value).strip().rstrip("%")))
    except (TypeError, ValueError):
        match = re.search(r"\d+", str(value))
        n = int(match.group()) if match else None
    if n is None or n < 0:
        return None
    return n


def to_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "si", "sí"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    return None


def to_list(value: Any) -> list[str]:
    if not value:
        return []
    items = value if isinstance(value, list) else re.split(r"[,;/]| and ", str(value))
    out = []
    for item in items:
        text = clean_str(item)
        if text and text.lower() not in {"none", "nobody", "no one"}:
            out.append(text.lower())
    return out


def normalize_phone(raw: Any) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    if "{{" in text or text.lower() in {"unknown", "none", "anonymous"}:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if 8 <= len(digits) <= 15 and text.startswith("+"):
        return "+" + digits
    return None


def case_number(case_id: int) -> str:
    return f"LF-{case_id + 1000}"


def case_number_spoken(case_id: int) -> str:
    return " ".join(DIGIT_WORDS[int(d)] for d in str(case_id + 1000))


def is_fake_phone(phone: str | None) -> bool:
    return not phone or phone.startswith(FAKE_PHONE_PREFIX)


def build_summary(c: dict) -> str:
    parts = []
    people = c.get("people_count")
    who = f"{people} {'person' if people == 1 else 'people'}" if people else "Unknown number of people"
    where = c.get("address") or c.get("landmark") or "location not given yet"
    area = f" ({c['neighborhood']})" if c.get("neighborhood") and c["neighborhood"] != "Houston area" else ""
    parts.append(f"{who} at {where}{area}.")
    water = normalize_water(c.get("water_level"))
    if water not in {"unknown", "none"}:
        parts.append(f"Water at {water}{' and rising' if c.get('water_rising') else ''}.")
    elif c.get("water_rising"):
        parts.append("Water rising.")
    if c.get("vulnerable"):
        parts.append(f"With: {', '.join(c['vulnerable'])}.")
    if c.get("medical_needs"):
        parts.append(f"Needs: {', '.join(c['medical_needs'])}.")
    if has_injury(c.get("injuries")):
        parts.append(f"Injury: {c['injuries']}.")
    return " ".join(parts)


def mask_phone(phone: str | None) -> str | None:
    """'+12814085709' -> '•••-•••-5709'. The full number never leaves the server."""
    digits = re.sub(r"\D", "", phone or "")
    return f"•••-•••-{digits[-4:]}" if digits else None


def serialize(c: dict) -> dict:
    """Case as sent to the dashboard (REST and /ws). Phones are masked; callbacks look the
    full number up server-side by case ID."""
    bonus = wait_bonus(c.get("created_at"), c.get("status"))
    priority = min(100, (c.get("base_priority") or 0) + bonus)
    out = {k: v for k, v in c.items() if k not in {"conversation_ids"}}
    for key in ("created_at", "updated_at", "assigned_at", "resolved_at"):
        if isinstance(out.get(key), datetime):
            out[key] = out[key].isoformat()
    out.update(
        case_number=case_number(c["id"]),
        priority=priority,
        wait_bonus=bonus,
        label=label_for(priority),
        can_call_back=not is_fake_phone(c.get("phone")) and elevenlabs.callback_ready(),
        phone=mask_phone(c.get("phone")),
    )
    return out


async def publish(case: dict, event: str = "case_upsert") -> dict:
    data = serialize(case)
    await hub.broadcast({"type": event, "case": data})
    return data


def _with_score(fields: dict, context: dict | None = None) -> dict:
    """Score `fields`. `context` is the stored case, so the rules can also read its transcript and notes."""
    score, reasons = base_score({**(context or {}), **fields})
    fields["base_priority"] = score
    fields["reasons"] = reasons
    if VERIFY_PEOPLE in reasons:  # e.g. a prank claiming 100 people: flag, never clear an existing flag
        fields["needs_review"] = True
        fields["review_reason"] = fields.get("review_reason") or "Unusually high people count: verify"
    if not fields.get("enriched"):
        fields["summary_en"] = build_summary(fields)
    return fields


# ---------- intake ----------

INCOMING_KEYS = (
    "caller_name", "language", "address", "landmark", "people_count", "water_level", "water_rising",
    "vulnerable", "medical_needs", "injuries", "life_threatening", "critical_reason", "battery_pct",
    "pets", "notes",
)


def normalize_incoming(raw: dict) -> dict:
    """Coerce whatever an agent/LLM sent into clean typed fields. Missing -> absent."""
    out: dict[str, Any] = {}
    for key in ("caller_name", "language", "address", "landmark", "injuries", "pets", "notes", "critical_reason"):
        text = clean_str(raw.get(key))
        if text:
            out[key] = text
    if (n := to_int(raw.get("people_count"))) is not None and n > 0:
        out["people_count"] = n
    if (b := to_int(raw.get("battery_pct"))) is not None and b <= 100:
        out["battery_pct"] = b
    if raw.get("water_level"):
        level = normalize_water(str(raw["water_level"]))
        if level != "unknown":
            out["water_level"] = level
    for key in ("water_rising", "life_threatening"):
        if (v := to_bool(raw.get(key))) is not None:
            out[key] = v
    for key in ("vulnerable", "medical_needs"):
        items = to_list(raw.get(key))
        if items:
            out[key] = items
    return out


def merge(existing: dict, incoming: dict) -> dict:
    merged = {k: existing.get(k) for k in INCOMING_KEYS}
    for key, value in incoming.items():
        if key in ("vulnerable", "medical_needs"):
            merged[key] = sorted(set((existing.get(key) or [])) | set(value))
        elif key == "life_threatening":
            merged[key] = bool(existing.get(key)) or value
        elif key == "notes" and existing.get("notes") and value not in existing["notes"]:
            merged[key] = f"{existing['notes']} | {value}"
        else:
            merged[key] = value
    merged["vulnerable"] = merged.get("vulnerable") or []
    merged["medical_needs"] = merged.get("medical_needs") or []
    merged["life_threatening"] = bool(merged.get("life_threatening"))
    return merged


async def _log_inbound_once(conversation_id: str | None, case: dict | None, phone: str | None,
                            kind: str = "inbound") -> None:
    if conversation_id:
        if conversation_id in _seen_conversations:
            return
        _seen_conversations.add(conversation_id)
    await db.add_call_event(
        kind,
        case_id=case["id"] if case else None,
        phone=phone,
        area=case.get("neighborhood") if case else None,
        language=case.get("language") if case else None,
    )


async def upsert_rescue(raw: dict, *, phone: str | None, conversation_id: str | None = None,
                        source: str = "call", enriched_summary: str | None = None) -> dict:
    """Create or update a case. Returns the saved row. Geocoding happens in the background."""
    async with _case_lock:
        return await _upsert_rescue(raw, phone=phone, conversation_id=conversation_id, source=source,
                                    enriched_summary=enriched_summary)


async def _upsert_rescue(raw: dict, *, phone: str | None, conversation_id: str | None,
                         source: str, enriched_summary: str | None) -> dict:
    incoming = normalize_incoming(raw)
    phone = phone or normalize_phone(raw.get("callback_number"))

    existing = await db.find_case_by_conversation(conversation_id) if conversation_id else None
    if not existing and phone:
        existing = await db.find_open_case_by_phone(phone)

    fields = merge(existing or {}, incoming)
    address_changed = bool(incoming.get("address")) and incoming.get("address") != (existing or {}).get("address")

    if existing:
        conv_ids = list(existing.get("conversation_ids") or [])
        new_conversation = bool(conversation_id) and conversation_id not in conv_ids
        if new_conversation:
            conv_ids.append(conversation_id)
            fields["call_count"] = (existing.get("call_count") or 1) + 1
        fields["conversation_ids"] = conv_ids
        fields["enriched"] = existing.get("enriched") and not incoming
        fields["location_confidence"] = "none" if address_changed else existing.get("location_confidence")
        fields["neighborhood"] = existing.get("neighborhood")
        if not existing.get("phone") and phone:
            fields["phone"] = phone
        if enriched_summary:
            fields["summary_en"], fields["enriched"] = enriched_summary, True
        _with_score(fields, context=existing)
        if fields.get("enriched") and existing.get("summary_en") and not enriched_summary:
            fields["summary_en"] = existing["summary_en"]
        case = await db.update_case(existing["id"], fields)
    else:
        fields.update(
            source=source,
            phone=phone,
            conversation_ids=[conversation_id] if conversation_id else [],
            location_confidence="none",
        )
        if enriched_summary:
            fields["summary_en"], fields["enriched"] = enriched_summary, True
        _with_score(fields)
        if enriched_summary:
            fields["summary_en"] = enriched_summary
        case = await db.insert_case(fields)

    await _log_inbound_once(conversation_id, case, phone, kind="social" if source == "social" else "inbound")
    await publish(case)
    if fields.get("life_threatening") and not (existing or {}).get("life_threatening"):
        await hub.broadcast({"type": "alert", "level": "critical", "case": serialize(case)})

    if address_changed or (case.get("lat") is None and (case.get("address") or case.get("landmark"))):
        spawn(locate(case["id"]))
    life = "LIFE-THREATENING. " if case.get("life_threatening") else ""
    spawn(memory.remember(phone, f"[{datetime.now(timezone.utc):%b %d %H:%M} UTC] {life}{case['summary_en']}",
                          case_number(case["id"])))
    return case


async def locate(case_id: int) -> None:
    case = await db.get_case(case_id)
    if not case:
        return
    address, landmark = case.get("address"), case.get("landmark")
    coords = await geocode(address, landmark)
    # Re-read: the caller may have updated the case while we were geocoding
    case = await db.get_case(case_id)
    if not case or (case.get("address"), case.get("landmark")) != (address, landmark):
        return  # address changed again; a newer locate() call will handle it
    fields: dict[str, Any] = {k: case.get(k) for k in INCOMING_KEYS}
    fields["enriched"] = case.get("enriched")
    if coords:
        fields.update(lat=coords[0], lng=coords[1], location_confidence="high",
                      neighborhood=nearest_area(*coords))
    elif (area := area_mentioned(" ".join(filter(None, [case.get("address"), case.get("landmark"),
                                                          case.get("notes")])))):
        # Couldn't geocode the street, but we know the neighborhood: drop an approximate pin
        fields.update(lat=area["lat"], lng=area["lng"], location_confidence="approximate",
                      neighborhood=area["name"])
    else:
        fields.update(location_confidence="none")
    fields["neighborhood"] = fields.get("neighborhood") or case.get("neighborhood")
    _with_score(fields, context=case)
    if case.get("enriched"):
        fields["summary_en"] = case["summary_en"]
    updated = await db.update_case(case_id, {k: v for k, v in fields.items() if k in
                                              {"lat", "lng", "location_confidence", "neighborhood",
                                               "base_priority", "reasons", "summary_en"}})
    if updated:
        await publish(updated)
        if updated.get("location_confidence") == "high":
            await merge_duplicates(case_id)


async def merge_duplicates(case_id: int) -> None:
    """If this newly located case is the same place as another active report, fold the newer one into
    the older one. The newer case is closed with a pointer, never deleted. Rules live in dedupe.py."""
    async with _case_lock:
        case = await db.get_case(case_id)
        if not case or not dedupe.mergeable(case):
            return
        rows = await db.pool.fetch(
            "select * from cases where id <> $1 and source <> 'simulated' and status in ('open','assigned') "
            "and location_confidence = 'high' and created_at > now() - interval '2 hours'", case_id)
        target = dedupe.find_target(case, [dict(r) for r in rows])
        if not target:
            return
        keep, drop = (target, case) if target["created_at"] <= case["created_at"] else (case, target)

        fields: dict[str, Any] = {k: keep.get(k) if keep.get(k) not in (None, "", []) else drop.get(k)
                                  for k in INCOMING_KEYS}
        for key in ("vulnerable", "medical_needs"):
            fields[key] = sorted(set(keep.get(key) or []) | set(drop.get(key) or []))
        fields["life_threatening"] = bool(keep.get("life_threatening") or drop.get("life_threatening"))
        reports = (keep.get("call_count") or 1) + (drop.get("call_count") or 1)
        note = f"Reported by {reports} sources"
        other_notes = re.sub(r"\s*\|?\s*Reported by \d+ sources\.?", "", fields.get("notes") or "").strip(" |")
        fields["notes"] = f"{other_notes} | {note}." if other_notes else f"{note}."
        fields.update(enriched=keep.get("enriched"), neighborhood=keep.get("neighborhood"), location_confidence="high")
        transcript = list(keep.get("transcript") or []) + list(drop.get("transcript") or [])
        transcript_en = list(keep.get("transcript_en") or []) + list(drop.get("transcript_en") or [])
        _with_score(fields, context={**keep, "transcript": transcript, "transcript_en": transcript_en})

        score = max(fields["base_priority"], keep.get("base_priority") or 0, drop.get("base_priority") or 0)
        reasons = fields["reasons"] + [note]
        if score > fields["base_priority"]:
            reasons.append(f"Kept the higher priority ({score}) from the merged reports")
        update = {k: fields[k] for k in INCOMING_KEYS}
        update.update(
            base_priority=score, reasons=reasons, call_count=reports, transcript=transcript,
            transcript_en=transcript_en or None,
            conversation_ids=sorted(set(keep.get("conversation_ids") or []) | set(drop.get("conversation_ids") or [])),
            phone=keep.get("phone") or drop.get("phone"),
            summary_en=keep["summary_en"] if keep.get("enriched") else fields["summary_en"],
            needs_review=bool(keep.get("needs_review") or drop.get("needs_review")),
            review_reason=keep.get("review_reason") or drop.get("review_reason"),
        )
        merged = await db.update_case(keep["id"], update)
        closed = await db.update_case(drop["id"], {
            "status": "closed", "resolved_at": datetime.now(timezone.utc), "conversation_ids": [],
            "notes": f"{drop.get('notes') or ''} | Merged into {case_number(keep['id'])}".strip(" |")})
    log.info("Merged %s into %s (%d reports)", case_number(drop["id"]), case_number(keep["id"]), reports)
    if closed:
        await publish(closed)
    if merged:
        await publish(merged)
        if merged.get("life_threatening") and not keep.get("life_threatening"):
            await hub.broadcast({"type": "alert", "level": "critical", "case": serialize(merged)})


async def set_location(case_id: int, lat: float, lng: float) -> dict:
    """Dispatcher dragged the pin to the right spot."""
    case = await db.get_case(case_id)
    if not case:
        raise LookupError("case not found")
    fields: dict[str, Any] = {k: case.get(k) for k in INCOMING_KEYS}
    fields.update(enriched=case.get("enriched"), lat=lat, lng=lng, location_confidence="high",
                  neighborhood=nearest_area(lat, lng))
    _with_score(fields, context=case)
    if case.get("enriched"):
        fields["summary_en"] = case["summary_en"]
    updated = await db.update_case(case_id, {k: fields[k] for k in
                                             ("lat", "lng", "location_confidence", "neighborhood",
                                              "base_priority", "reasons", "summary_en")})
    await publish(updated)
    return updated


async def flag_critical(raw: dict, *, phone: str | None, conversation_id: str | None) -> dict:
    data = {
        "life_threatening": True,
        "critical_reason": raw.get("reason"),
        "address": raw.get("address"),
        "callback_number": raw.get("callback_number"),
    }
    return await upsert_rescue(data, phone=phone, conversation_id=conversation_id)


async def lookup(phone: str | None, conversation_id: str | None) -> dict:
    async with _case_lock:
        case = await db.find_open_case_by_phone(phone) if phone else None
        await _log_inbound_once(conversation_id, case, phone)
        if case and conversation_id and conversation_id not in (case.get("conversation_ids") or []):
            conv_ids = list(case.get("conversation_ids") or []) + [conversation_id]
            case = await db.update_case(case["id"], {"conversation_ids": conv_ids,
                                                     "call_count": (case.get("call_count") or 1) + 1})
    if case:
        await publish(case)
    history = await memory.recall(phone) if phone else []

    if not case:
        return {
            "known": False,
            "history": history[:3],
            "say": "No open request for this number. Collect details as normal.",
        }

    say = f"This caller already has open request case {case_number_spoken(case['id'])}."
    if case.get("status") == "assigned" and case.get("unit"):
        say += " A team has been assigned. You may tell them a team has been assigned, but never give a time."
    else:
        say += " Not yet assigned. Ask only what changed and call submit_rescue_request with updates."
    return {
        "known": True,
        "case_number": case_number(case["id"]),
        "case_number_spoken": case_number_spoken(case["id"]),
        "caller_name": case.get("caller_name") or "",
        "address": case.get("address") or "",
        "status": case.get("status"),
        "unit": case.get("unit") or "",
        "history": history[:5],
        "say": say,
    }


# ---------- dispatcher actions ----------

async def assign(case_id: int, unit: str, eta_minutes: int | None, call_back: bool = True) -> dict:
    case = await db.get_case(case_id)
    if not case:
        raise LookupError("case not found")
    fields = {
        "status": "assigned",
        "unit": unit,
        "eta_minutes": eta_minutes,
        "assigned_at": datetime.now(timezone.utc),
    }
    will_call = call_back and not is_fake_phone(case.get("phone")) and elevenlabs.callback_ready()
    if will_call:
        fields["callback_status"] = "calling"
    elif call_back and is_fake_phone(case.get("phone")):
        fields["callback_status"] = "no phone (simulated)"
    elif call_back:
        fields["callback_status"] = "callback not configured"
    case = await db.update_case(case_id, fields)
    await publish(case)
    if will_call:
        spawn(_place_callback(case))
    spawn(memory.remember(case.get("phone"), f"Assigned {unit}, ETA about {eta_minutes} minutes.",
                          case_number(case_id)))
    return case


async def _place_callback(case: dict) -> None:
    name = case.get("caller_name") or ""
    variables = {
        "case_id": str(case["id"]),
        "case_number_spoken": case_number_spoken(case["id"]),
        "caller_name": name,
        "caller_name_greeting": f" {name.split()[0]}" if name else "",
        "address": case.get("address") or case.get("landmark") or "the location you gave",
        "people_count": str(case.get("people_count") or "unknown"),
        "unit": case.get("unit") or "A rescue team",
        "eta_minutes": str(case.get("eta_minutes") or "unknown"),
        "language": case.get("language") or "English",
    }
    english_first = (f"Hello{variables['caller_name_greeting']}, this is Lifeline calling back about your rescue "
                     f"request, case {variables['case_number_spoken']}. A rescue team has been assigned to you.")
    first_message = await gemini.translate(english_first, variables["language"]) or english_first
    result = await elevenlabs.start_outbound_call(case["phone"], variables, first_message, variables["language"])
    status = "ringing" if result["ok"] else f"failed: {result.get('error', 'unknown error')}"
    conv_ids = list(case.get("conversation_ids") or [])
    if result.get("conversation_id"):
        conv_ids.append(result["conversation_id"])
    updated = await db.update_case(case["id"], {"callback_status": status, "conversation_ids": conv_ids})
    if result["ok"]:
        await db.add_call_event("callback", case_id=case["id"], phone=case["phone"],
                                area=case.get("neighborhood"), language=case.get("language"))
    if updated:
        await publish(updated)


async def set_status(case_id: int, status: str) -> dict:
    if status not in {"open", "assigned", "rescued", "closed"}:
        raise ValueError("bad status")
    fields: dict[str, Any] = {"status": status}
    if status in {"rescued", "closed"}:
        fields["resolved_at"] = datetime.now(timezone.utc)
    if status == "open":
        fields.update(unit=None, eta_minutes=None, assigned_at=None, resolved_at=None, callback_status=None)
    case = await db.update_case(case_id, fields)
    if not case:
        raise LookupError("case not found")
    await publish(case)
    spawn(memory.remember(case.get("phone"), f"Case marked {status} by dispatcher.", case_number(case_id)))
    return case


async def update_from_callback(raw: dict) -> dict:
    case_id = to_int(raw.get("case_id"))
    case = await db.get_case(case_id) if case_id is not None else None
    if not case:
        return {"ok": False, "say": "I couldn't find that case. Tell them a dispatcher will follow up."}
    incoming = normalize_incoming({
        "address": raw.get("new_address"),
        "water_level": raw.get("water_level"),
        "water_rising": raw.get("water_rising"),
        "injuries": raw.get("injuries"),
        "life_threatening": raw.get("life_threatening"),
        "notes": raw.get("notes"),
    })
    fields = merge(case, incoming)
    status_text = (clean_str(raw.get("status")) or "").lower()
    if status_text == "safe":
        fields.update(status="rescued", resolved_at=datetime.now(timezone.utc))
        fields["notes"] = ((fields.get("notes") or "") + " | Caller reports safe on callback").strip(" |")
    fields["enriched"] = False
    fields["neighborhood"] = case.get("neighborhood")
    fields["location_confidence"] = "none" if incoming.get("address") else case.get("location_confidence")
    _with_score(fields, context=case)
    updated = await db.update_case(case["id"], fields)
    await publish(updated)
    if incoming.get("life_threatening") and not case.get("life_threatening"):
        await hub.broadcast({"type": "alert", "level": "critical", "case": serialize(updated)})
    if incoming.get("address"):
        spawn(locate(case["id"]))
    spawn(memory.remember(case.get("phone"), f"Callback update: {updated['summary_en']}", case_number(case["id"])))
    return {"ok": True, "say": "Updated. A dispatcher can see the change."}


# ---------- post-call webhook ----------

def _transcript_lines(data: dict, call: str) -> list[dict]:
    lines = []
    for turn in data.get("transcript") or []:
        message = (turn.get("message") or "").strip()
        if message:
            lines.append({"role": turn.get("role"), "message": message, "call": call,
                          "t": turn.get("time_in_call_secs")})
    return lines


async def handle_post_call(event: dict) -> None:
    if event.get("type") != "post_call_transcription":
        return
    data = event.get("data") or {}
    conversation_id = data.get("conversation_id")
    client_data = data.get("conversation_initiation_client_data") or {}
    variables = client_data.get("dynamic_variables") or {}
    phone_meta = ((data.get("metadata") or {}).get("phone_call") or {})
    phone = normalize_phone(variables.get("system__caller_id") or phone_meta.get("external_number"))
    duration = (data.get("metadata") or {}).get("call_duration_secs")

    from . import config
    is_callback = bool(variables.get("case_id")) or (config.CALLBACK_AGENT_ID and data.get("agent_id") == config.CALLBACK_AGENT_ID)

    if is_callback:
        case = await db.get_case(to_int(variables.get("case_id")) or -1) or \
            await db.find_case_by_conversation(conversation_id)
        if case:
            transcript = list(case.get("transcript") or []) + _transcript_lines(data, "callback")
            updated = await db.update_case(case["id"], {"transcript": transcript, "callback_status": "completed"})
            await publish(updated)
        return

    lines = _transcript_lines(data, "intake")
    case = await db.find_case_by_conversation(conversation_id)
    if not case and phone:
        case = await db.find_open_case_by_phone(phone)

    if case:
        transcript = list(case.get("transcript") or []) + lines
        case = await db.update_case(case["id"], {"transcript": transcript})
        await publish(case)
        await enrich(case["id"], lines)
        return

    # The call ended before submit_rescue_request: rebuild the request from the transcript.
    log.info("Call %s ended with no case. Transcript: %s", conversation_id,
             " | ".join(f"{l['role']}: {l['message']}" for l in lines)[:1000])
    if not any(l["role"] == "user" for l in lines):
        return
    extraction = await gemini.extract_from_transcript(lines)
    if not extraction or not extraction.get("is_rescue_request") or not (extraction.get("address") or extraction.get("landmark")):
        log.info("Dropped call %s had no usable rescue details", conversation_id)
        return
    case = await upsert_rescue(extraction, phone=phone, conversation_id=conversation_id, source="dropped_call",
                               enriched_summary=extraction.get("summary_en"))
    await db.update_case(case["id"], {"transcript": lines,
                                      "transcript_en": [l for l in extraction.get("transcript_en") or []] or None})
    if duration:
        await db.add_call_event("inbound", case_id=case["id"], phone=phone, duration_s=int(duration))
    await ground(case["id"])
    refreshed = await db.get_case(case["id"])
    if refreshed:
        await publish(refreshed)


async def enrich(case_id: int, lines: list[dict]) -> None:
    """Gemini pass after a call: translate, summarize, and fill gaps the agent missed."""
    extraction = await gemini.extract_from_transcript(lines)
    if not extraction:
        await ground(case_id)  # doesn't need Gemini
        return
    case = await db.get_case(case_id)
    if not case:
        return
    gaps = {}
    for key in INCOMING_KEYS:
        current = case.get(key)
        value = extraction.get(key)
        if key in ("vulnerable", "medical_needs"):
            if value:
                gaps[key] = value
        elif key == "life_threatening":
            if value and not current:
                gaps[key] = True
        elif key == "people_count":
            if not current and value:
                gaps[key] = value
        elif key == "battery_pct":
            if current is None and isinstance(value, int) and value >= 0:
                gaps[key] = value
        elif key == "water_level":
            if normalize_water(current) == "unknown" and value and value != "unknown":
                gaps[key] = value
        elif not current and value:
            gaps[key] = value
    incoming = normalize_incoming(gaps)
    fields = merge(case, incoming)
    fields["neighborhood"] = case.get("neighborhood")
    fields["location_confidence"] = case.get("location_confidence")
    fields["enriched"] = True
    _with_score(fields, context=case)
    fields["summary_en"] = extraction.get("summary_en") or build_summary(fields)
    fields["enriched"] = True
    translated = extraction.get("transcript_en") or []
    if translated:
        fields["transcript_en"] = translated
    updated = await db.update_case(case_id, fields)
    if updated:
        await publish(updated)
        if incoming.get("address") and updated.get("lat") is None:
            spawn(locate(case_id))
    await ground(case_id)


async def ground(case_id: int) -> None:
    """Clear critical details the caller never actually said, and flag the case for review."""
    case = await db.get_case(case_id)
    if not case:
        return
    changes = grounding.check(case)
    if not changes:
        return
    log.info("%s: AI details not found in what the caller said, cleared: %s", case_number(case_id),
             ", ".join(k for k in changes if k not in {"needs_review", "review_reason"}))
    fields: dict[str, Any] = {k: case.get(k) for k in INCOMING_KEYS}
    fields.update({k: v for k, v in changes.items() if k in INCOMING_KEYS})
    fields.update(enriched=case.get("enriched"), neighborhood=case.get("neighborhood"),
                  location_confidence=case.get("location_confidence"))
    _with_score(fields, context=case)
    if case.get("enriched"):
        fields["summary_en"] = case["summary_en"]
    updated = await db.update_case(case_id, {**changes, "base_priority": fields["base_priority"],
                                             "reasons": fields["reasons"], "summary_en": fields["summary_en"]})
    if updated:
        await publish(updated)
