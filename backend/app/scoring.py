"""Deterministic triage score.

Gemini and the voice agent only extract facts. The score is plain rules, so it
is the same every time and every point can be explained to a dispatcher.
"""

import re
from datetime import datetime, timezone

WATER_POINTS = {
    "roof": 40,
    "chest": 32,
    "waist": 24,
    "knee": 12,
    "ankle": 5,
    "none": 0,
    "unknown": 10,
}

LIFE_SUPPORT_WORDS = (
    "oxygen", "dialysis", "insulin", "ventilator", "cpap", "medication", "meds",
    "medicine", "seizure", "heart", "chemo", "wheelchair", "feeding tube",
)

VULNERABLE_GROUPS = {
    "elderly": ("elderly", "senior", "old", "grand"),
    "baby or child": ("baby", "infant", "child", "kid", "toddler", "newborn"),
    "disabled": ("disab", "wheelchair", "bedridden", "blind", "deaf"),
    "pregnant": ("pregnan",),
}

# Someone who can't get out on their own: these words anywhere in the case, or elderly/disabled, AND alone
MOBILITY_WORDS = ("wheelchair", "bedbound", "bed-bound", "bed bound", "bedridden", "can't walk", "cannot walk",
                  "immobile", "paraly")
CANT_EVACUATE_POINTS = 10

RED, ORANGE = 60, 35
WAIT_BONUS_EVERY_MIN = 10
WAIT_BONUS_MAX = 20


def normalize_water(level: str | None) -> str:
    if not level:
        return "unknown"
    text = level.strip().lower()
    for key in ("roof", "chest", "waist", "knee", "ankle"):
        if key in text:
            return key
    if text in {"none", "no", "dry", "no water"}:
        return "none"
    return "unknown"


def cant_evacuate_alone(case: dict) -> bool:
    notes = (case.get("notes") or "").lower()
    text = " ".join([*(case.get("vulnerable") or []), *(case.get("medical_needs") or []),
                     case.get("injuries") or "", notes]).lower()
    vulnerable = " ".join(case.get("vulnerable") or []).lower()
    limited = any(w in text for w in MOBILITY_WORDS) or any(
        w in vulnerable for w in VULNERABLE_GROUPS["elderly"] + VULNERABLE_GROUPS["disabled"])
    alone = case.get("people_count") == 1 or bool(re.search(r"\balone\b|by (him|her|them)sel(f|ves)", notes))
    return limited and alone


def base_score(case: dict) -> tuple[int, list[str]]:
    points = 0
    reasons: list[str] = []

    if case.get("life_threatening"):
        points += 30
        reasons.append("Life-threatening (+30)")

    water = normalize_water(case.get("water_level"))
    wp = WATER_POINTS[water]
    if wp:
        label = "unknown water level" if water == "unknown" else f"water at {water}"
        reasons.append(f"{label.capitalize()} (+{wp})")
        points += wp

    if case.get("water_rising"):
        points += 10
        reasons.append("Water rising (+10)")

    medical = " ".join(case.get("medical_needs") or []).lower()
    if medical and any(w in medical for w in LIFE_SUPPORT_WORDS):
        points += 15
        reasons.append("Depends on medicine or power (+15)")

    if (case.get("injuries") or "").strip():
        points += 10
        reasons.append("Injury reported (+10)")

    vulnerable_text = " ".join(case.get("vulnerable") or []).lower()
    groups = [g for g, words in VULNERABLE_GROUPS.items() if any(w in vulnerable_text for w in words)]
    if groups:
        vp = min(16, 8 * len(groups))
        points += vp
        reasons.append(f"Vulnerable: {', '.join(groups)} (+{vp})")

    people = case.get("people_count") or 0
    if people:
        pp = min(10, 2 * people)
        points += pp
        reasons.append(f"{people} {'person' if people == 1 else 'people'} (+{pp})")

    evac_floor = 0
    if cant_evacuate_alone(case):
        evac_floor = RED if case.get("water_rising") else ORANGE
        points += CANT_EVACUATE_POINTS
        reasons.append(f"Can't evacuate alone (+{CANT_EVACUATE_POINTS}, at least "
                       f"{'Immediate because water is rising' if evac_floor == RED else 'Urgent'})")

    battery = case.get("battery_pct")
    if battery is not None and battery <= 15:
        points += 5
        reasons.append(f"Phone at {battery}%, may lose contact (+5)")

    if case.get("location_confidence") == "none" and (case.get("address") or case.get("landmark")):
        reasons.append("Location not confirmed on map: check address")
    elif case.get("location_confidence") == "approximate":
        reasons.append("Pin is approximate (neighborhood only): confirm address")

    points = min(100, points)
    if case.get("life_threatening"):
        points = max(points, 70)
    if points < evac_floor:
        reasons.append(f"Raised from {points} to {evac_floor}: can't evacuate alone")
        points = evac_floor
    return points, reasons


def wait_bonus(created_at: datetime | None, status: str | None) -> int:
    if not created_at or status != "open":
        return 0
    minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
    return int(min(WAIT_BONUS_MAX, minutes // WAIT_BONUS_EVERY_MIN))


def label_for(score: int) -> str:
    if score >= RED:
        return "red"
    if score >= ORANGE:
        return "orange"
    return "yellow"
