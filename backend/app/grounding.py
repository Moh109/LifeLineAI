"""Grounding check: AI-filled critical details must appear in what the caller actually said.

Runs once the transcript is in (after the call, or for a pasted post). For critical_reason,
injuries and medical_needs, at least one meaningful word (or a close variant: same first
5 letters) has to show up in the caller's own turns. Agent turns never count. For non-English
calls the English translation (transcript_en) is checked too, so a Spanish call is never
flagged just because of the language.
"""

import re

REVIEW_REASON = "AI detail not found in call"

STOPWORDS = {
    "the", "and", "with", "from", "after", "being", "that", "this", "have", "been", "their", "there",
    "they", "them", "into", "about", "very", "some", "possible", "possibly", "reported", "report",
    "caller", "person", "people", "someone", "needs", "need", "needed", "heavily", "severe", "while",
    "were", "also", "only", "still", "just", "other", "unknown", "none",
    # flood context: almost every caller says these, so they prove nothing about the specific claim
    "water", "flood", "flooding", "flooded", "rising", "house", "home", "help", "emergency", "rescue",
    "trapped", "stuck", "right", "here",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-záéíóúñü']+", (text or "").lower())


COMMON_ENGLISH = set("""
a about after all am an and any are at be been but by can can't come could did do don't down for from get go
going got had has have he help her here him his how i i'm in is it it's just know like me mine my no not now
of off oh ok okay on one or our out over please right she so some than that the their them then there they
this to two up us very was water we were what when where who will with yes you your hello hi sir ma'am thank
thanks street house dad mom son daughter baby people need needs stuck trapped hurt is isn't we're he's she's
""".split())


def _mostly_not_english(text: str) -> bool:
    words = _words(text)
    if len(words) < 4:
        return False
    return sum(w in COMMON_ENGLISH for w in words) / len(words) < 0.25


def caller_text(case: dict) -> str:
    """Everything the caller said: original turns plus the English translation of their turns."""
    parts = [l.get("message", "") for l in case.get("transcript") or [] if l.get("role") == "user"]
    parts += [l.get("message", "") for l in case.get("transcript_en") or []
              if (l.get("role") or "").lower() in {"caller", "user"}]
    return " ".join(parts)


def is_grounded(value: str, said: str) -> bool:
    keywords = [w for w in _words(value) if len(w) >= 4 and w not in STOPWORDS]
    if not keywords:
        return True  # nothing checkable (e.g. "cut"), don't flag
    said_stems = {w[:5] for w in _words(said)}
    return any(k[:5] in said_stems for k in keywords)


def check(case: dict) -> dict | None:
    """Return the fields to update if something isn't grounded, else None.
    Skips cases with no caller turns (nothing to check against yet)."""
    said = caller_text(case)
    if not said.strip():
        return None
    # A caller turn in another language with no English translation can't be checked fairly: skip, don't flag
    if not case.get("transcript_en") and any(
            _mostly_not_english(l.get("message", "")) for l in case.get("transcript") or [] if l.get("role") == "user"):
        return None
    changes: dict = {}
    for key in ("critical_reason", "injuries"):
        value = case.get(key)
        if value and not is_grounded(value, said):
            changes[key] = None
    meds = case.get("medical_needs") or []
    kept = [m for m in meds if is_grounded(m, said)]
    if len(kept) != len(meds):
        changes["medical_needs"] = kept
    if changes:
        changes["needs_review"] = True
        changes["review_reason"] = REVIEW_REASON
    return changes or None
