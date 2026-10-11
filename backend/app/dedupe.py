"""Duplicate reports: two callers describing the same place become one case.

A case can only be merged once it has a confirmed pin (location_confidence = "high").
It merges into an open or assigned case from the last 2 hours that is within ~75 m or has
the same normalized address. Simulated (surge) cases never merge, and closed or rescued
cases are never merge targets.
"""

import math
import re
from datetime import timedelta

MERGE_RADIUS_M = 75
MERGE_WINDOW = timedelta(hours=2)
ACTIVE = {"open", "assigned"}

SUFFIXES = {"street": "st", "avenue": "ave", "drive": "dr", "road": "rd", "boulevard": "blvd", "lane": "ln",
            "parkway": "pkwy", "freeway": "fwy", "highway": "hwy", "court": "ct", "place": "pl", "circle": "cir"}
NOISE = {"houston", "texas", "tx", "usa", "us"}


def normalize_address(address: str | None) -> str:
    words = re.findall(r"[a-z0-9]+", (address or "").lower())
    words = [SUFFIXES.get(w, w) for w in words if w not in NOISE and not re.fullmatch(r"\d{5}", w)]
    return " ".join(words)


def distance_m(a: dict, b: dict) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def mergeable(case: dict) -> bool:
    return (case.get("source") != "simulated" and case.get("status") in ACTIVE
            and case.get("location_confidence") == "high" and case.get("lat") is not None)


def same_place(a: dict, b: dict) -> bool:
    if distance_m(a, b) <= MERGE_RADIUS_M:
        return True
    na, nb = normalize_address(a.get("address")), normalize_address(b.get("address"))
    return bool(na) and na == nb


def find_target(case: dict, others: list[dict]) -> dict | None:
    """The earliest active case (other than `case`) that this case duplicates, within the time window."""
    if not mergeable(case):
        return None
    matches = [o for o in others
               if o["id"] != case["id"] and mergeable(o)
               and abs(o["created_at"] - case["created_at"]) <= MERGE_WINDOW
               and same_place(case, o)]
    return min(matches, key=lambda o: o["created_at"], default=None)
