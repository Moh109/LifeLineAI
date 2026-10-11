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
                  "unable to walk", "can't move", "cannot move", "unable to move", "immobile", "paraly")
CANT_EVACUATE_POINTS = 10

# Injury text that means "no injury"
NO_INJURY = {"none", "none reported", "no", "n/a", "na", "no injuries", "no injury", "not reported", "nobody",
             "nothing", "unknown", "nil"}
FLOOD_WORDS = re.compile(r"\b(water|flood\w*|drown\w*|bayou|river|rain\w*)\b")
PEOPLE_VERIFY_OVER = 20
VERIFY_PEOPLE = "Verify: unusually high people count"

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


def vulnerable_words(case: dict) -> str:
    """The vulnerable list plus what the caller's stated age implies: 65+ is elderly, 12 or under is a child."""
    words = list(case.get("vulnerable") or [])
    ages = [int(n) for n in re.findall(r"\b\d{1,3}\b", str(case.get("age") or "")) if int(n) <= 120]
    if any(a >= 65 for a in ages):
        words.append("elderly")
    if any(a <= 12 for a in ages):
        words.append("child")
    return " ".join(words).lower()


def case_text(case: dict) -> str:
    """Everything said or written about the case (caller turns, translation, notes, summary). Lowercase."""
    parts = [case.get(k) or "" for k in ("notes", "critical_reason", "injuries", "summary_en", "landmark")]
    parts += [l.get("message", "") for l in case.get("transcript") or [] if l.get("role") == "user"]
    parts += [l.get("message", "") for l in case.get("transcript_en") or []
              if (l.get("role") or "").lower() in {"caller", "user"}]
    return " ".join(parts).lower()


def has_injury(injuries: str | None) -> bool:
    text = re.sub(r"[.!\s]+$", "", (injuries or "").strip().lower())
    return bool(text) and text not in NO_INJURY and not text.startswith(("no ", "none"))


def flood_related(case: dict) -> bool:
    level = (case.get("water_level") or "").strip()
    return bool(level) or bool(case.get("water_rising")) or bool(FLOOD_WORDS.search(case_text(case)))


def cant_evacuate_alone(case: dict) -> bool:
    text = " ".join([*(case.get("vulnerable") or []), *(case.get("medical_needs") or []), case_text(case)]).lower()
    vulnerable = vulnerable_words(case)
    limited = any(w in text for w in MOBILITY_WORDS) or any(
        w in vulnerable for w in VULNERABLE_GROUPS["elderly"] + VULNERABLE_GROUPS["disabled"])
    alone = case.get("people_count") == 1 or bool(re.search(r"\balone\b|by (him|her|them)sel(f|ves)", text))
    return limited and alone


def base_score(case: dict) -> tuple[int, list[str]]:
    points = 0
    reasons: list[str] = []

    if case.get("life_threatening"):
        points += 30
        reasons.append("Life-threatening (+30)")

    water = normalize_water(case.get("water_level"))
    wp = WATER_POINTS[water] if flood_related(case) else 0  # no water points for a gunshot, fire, etc.
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

    if has_injury(case.get("injuries")):
        points += 10
        reasons.append("Injury reported (+10)")

    vulnerable_text = vulnerable_words(case)
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
        if people > PEOPLE_VERIFY_OVER:
            reasons.append(VERIFY_PEOPLE)

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
