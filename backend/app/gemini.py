"""Gemini: turns call transcripts and social posts into structured rescue data.

Gemini extracts and translates. It never scores or decides; scoring.py does that.
Every function returns None when Gemini is off or fails, and callers fall back.
"""

import json
import logging

from pydantic import BaseModel, Field

from . import config

log = logging.getLogger("lifeline.gemini")

_clients: dict[int, object] = {}


class QuotaExhausted(Exception):
    """Every key is out of quota on both the main and the backup model."""


def _client(i: int):
    if i not in _clients:
        from google import genai

        _clients[i] = genai.Client(api_key=config.GEMINI_API_KEYS[i])
    return _clients[i]


def _is_quota_error(exc: Exception) -> bool:
    return getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc)


async def _with_fallback(call):
    """Run call(client, model). On a quota error, retry with the next key, then the backup model.
    Logs key numbers (key 1, key 2...) only, never the key."""
    models = [config.GEMINI_MODEL]
    if config.GEMINI_BACKUP_MODEL and config.GEMINI_BACKUP_MODEL != config.GEMINI_MODEL:
        models.append(config.GEMINI_BACKUP_MODEL)
    for model in models:
        for i in range(len(config.GEMINI_API_KEYS)):
            try:
                return await call(_client(i), model)
            except Exception as exc:
                if not _is_quota_error(exc):
                    raise
                log.warning("Gemini key %d is out of quota for %s; trying the next one", i + 1, model)
    raise QuotaExhausted(f"all {len(config.GEMINI_API_KEYS)} Gemini keys are out of quota on {', '.join(models)}")


class TranscriptLine(BaseModel):
    role: str = Field(description="'caller' or 'agent'")
    message: str = Field(description="The line translated to English")


class RescueExtraction(BaseModel):
    is_rescue_request: bool = Field(description="True if someone needs rescue or emergency help")
    language: str = Field(description="Main language the person spoke, e.g. English, Spanish, Vietnamese")
    caller_name: str = Field(default="", description="Name of the person asking for help, empty if unknown")
    address: str = Field(default="", description="Street address or cross streets where people need rescue, empty if unknown")
    landmark: str = Field(default="", description="Nearby landmark, empty if none")
    people_count: int = Field(default=0, description="Number of people needing rescue, 0 if unknown")
    water_level: str = Field(default="unknown", description="One of: none, ankle, knee, waist, chest, roof, unknown")
    water_rising: bool = Field(default=False)
    vulnerable: list[str] = Field(default_factory=list, description="Any of: elderly, baby, child, pregnant, disabled")
    medical_needs: list[str] = Field(default_factory=list, description="e.g. insulin, oxygen, dialysis, ventilator")
    injuries: str = Field(default="", description="Short English description of injuries, empty if none")
    life_threatening: bool = Field(default=False, description="Someone not breathing, unconscious, bleeding heavily, or in water over their head")
    battery_pct: int = Field(default=-1, description="Phone battery percent, -1 if unknown")
    pets: str = Field(default="")
    callback_number: str = Field(default="", description="Phone number to call back, empty if not given")
    summary_en: str = Field(description="Two short English sentences a dispatcher can read in 5 seconds")
    transcript_en: list[TranscriptLine] = Field(default_factory=list, description="English translation of every line, only if the original was not English; otherwise empty")


EXTRACT_PROMPT = """You help human flood-rescue dispatchers in Houston.
Read the {kind} below and extract ONLY facts the caller (or post author) actually said. Do not guess.
If something is not stated, leave it empty / unknown.
Never infer injuries, medical needs, or a life threat. Only fill injuries, medical_needs and
life_threatening if the caller said them in their own words. Questions the agent asked are not facts.
Write summary_en for a dispatcher: who, where, how many, water level, the most urgent risk.
{translation_rule}

{kind_title}:
{text}
"""


async def _generate(prompt: str) -> dict | None:
    if not config.GEMINI_API_KEYS:
        return None
    from google.genai import types

    async def structured(client, model):
        resp = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RescueExtraction,
                temperature=0.1,
            ),
        )
        return json.loads(resp.text)

    async def plain(client, model):
        schema_hint = json.dumps(RescueExtraction.model_json_schema())
        resp = await client.aio.models.generate_content(
            model=model,
            contents=prompt + "\nRespond with one JSON object matching this JSON schema:\n" + schema_hint,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
        )
        return json.loads(resp.text)

    try:
        return await _with_fallback(structured)
    except QuotaExhausted as exc:
        log.error("Gemini call failed: %s", exc)
        return None
    except Exception as exc:
        log.warning("Gemini structured call failed (%s); retrying with plain JSON", exc)
    try:
        return await _with_fallback(plain)
    except Exception as exc:
        log.error("Gemini call failed: %s", exc)
        return None


def _clean(data: dict | None) -> dict | None:
    if not data:
        return None
    try:
        return RescueExtraction.model_validate(data).model_dump()
    except Exception as exc:
        log.warning("Gemini returned unexpected shape: %s", exc)
        return None


async def extract_from_transcript(lines: list[dict]) -> dict | None:
    text = "\n".join(
        f"{'Caller' if l.get('role') == 'user' else 'Agent'}: {l.get('message', '')}" for l in lines if l.get("message")
    )
    if not text.strip():
        return None
    prompt = EXTRACT_PROMPT.format(
        kind="phone call transcript between a caller and the Lifeline voice agent",
        kind_title="Transcript",
        translation_rule="If the call was not in English, fill transcript_en with an English translation of each line (role 'caller' or 'agent').",
        text=text,
    )
    return _clean(await _generate(prompt))


async def extract_from_text(text: str) -> dict | None:
    prompt = EXTRACT_PROMPT.format(
        kind="social media post or text message",
        kind_title="Post",
        translation_rule="Leave transcript_en empty.",
        text=text.strip(),
    )
    return _clean(await _generate(prompt))


async def translate(text: str, language: str) -> str | None:
    if not config.GEMINI_API_KEYS or not language or language.lower().startswith("english"):
        return None

    async def call(client, model):
        return await client.aio.models.generate_content(
            model=model,
            contents=(
                f"Translate this phone greeting into {language}. Keep it warm and natural, "
                f"keep numbers as they are, and reply with only the translation:\n\n{text}"
            ),
        )

    try:
        resp = await _with_fallback(call)
        return (resp.text or "").strip() or None
    except Exception as exc:
        log.warning("Gemini translate failed: %s", exc)
        return None
