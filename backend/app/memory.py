"""Backboard: long-term memory of callers across calls.

The Postgres case record is the source of truth for the *current* request.
Backboard remembers what each caller told us on every call, so a repeat caller
(or a callback days later) gets context like "second call, water rose from knee
to chest, mother on oxygen" instead of starting over.
"""

import logging
import re

import httpx

from . import config

log = logging.getLogger("lifeline.memory")

BASE = "https://app.backboard.io/api"
_assistant_id: str | None = config.BACKBOARD_ASSISTANT_ID or None


def enabled() -> bool:
    return bool(config.BACKBOARD_API_KEY)


def _headers() -> dict:
    return {"X-API-Key": config.BACKBOARD_API_KEY, "Content-Type": "application/json"}


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")[-10:]


async def ensure_assistant() -> str | None:
    global _assistant_id
    if not enabled():
        return None
    if _assistant_id:
        return _assistant_id
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{BASE}/assistants",
                headers=_headers(),
                json={
                    "name": "Lifeline caller memory",
                    "system_prompt": "You store facts about people who called a flood-rescue line, keyed by phone number.",
                },
            )
            r.raise_for_status()
            _assistant_id = r.json()["assistant_id"]
        log.warning("Created Backboard assistant. Put this in .env: BACKBOARD_ASSISTANT_ID=%s", _assistant_id)
    except Exception as exc:
        log.error("Backboard assistant setup failed: %s", exc)
        return None
    return _assistant_id


async def remember(phone: str | None, fact: str, case_number: str | None = None) -> None:
    digits = _digits(phone)
    if not enabled() or not digits or not fact:
        return
    assistant = await ensure_assistant()
    if not assistant:
        return
    content = f"Caller {digits}: {fact}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{BASE}/assistants/{assistant}/memories",
                headers=_headers(),
                json={"content": content, "metadata": {"phone": digits, "case": case_number or ""}},
            )
            r.raise_for_status()
    except Exception as exc:
        log.warning("Backboard remember failed: %s", exc)


async def recall(phone: str | None, limit: int = 8) -> list[str]:
    """Return remembered facts for this phone number, most relevant first."""
    digits = _digits(phone)
    if not enabled() or not digits:
        return []
    assistant = await ensure_assistant()
    if not assistant:
        return []
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.post(
                f"{BASE}/assistants/{assistant}/memories/search",
                headers=_headers(),
                json={"query": f"Caller {digits} flood rescue history", "limit": limit},
            )
            r.raise_for_status()
            memories = r.json().get("memories", [])
    except Exception as exc:
        log.warning("Backboard recall failed: %s", exc)
        return []
    facts = []
    for m in memories:
        content = m.get("content") or ""
        if digits in re.sub(r"\D", "", content):
            facts.append(re.sub(rf"^Caller \+?\d*{digits}:\s*", "", content))
    return facts
