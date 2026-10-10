"""Gemini: turns call transcripts and social posts into structured rescue data.

Gemini extracts and translates. It never scores or decides; scoring.py does that.
Every function returns None when Gemini is off or fails, and callers fall back.
"""

import json
import logging

from pydantic import BaseModel, Field

from . import config

log = logging.getLogger("lifeline.gemini")

_client = None


def _get_client():
    global _client
    if _client is None and config.GEMINI_API_KEY:
        from google import genai

        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


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
Read the {kind} below and extract ONLY facts that are stated. Do not guess.
If something is not stated, leave it empty / unknown.
Write summary_en for a dispatcher: who, where, how many, water level, the most urgent risk.
{translation_rule}

{kind_title}:
{text}
"""


async def _generate(prompt: str) -> dict | None:
    client = _get_client()
    if not client:
        return None
    from google.genai import types

    try:
        resp = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RescueExtraction,
                temperature=0.1,
            ),
        )
        return json.loads(resp.text)
    except Exception as exc:
        log.warning("Gemini structured call failed (%s); retrying with plain JSON", exc)
    try:
        schema_hint = json.dumps(RescueExtraction.model_json_schema())
        resp = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt + "\nRespond with one JSON object matching this JSON schema:\n" + schema_hint,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
        )
        return json.loads(resp.text)
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
    client = _get_client()
    if not client or not language or language.lower().startswith("english"):
        return None
    try:
        resp = await client.aio.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=(
                f"Translate this phone greeting into {language}. Keep it warm and natural, "
                f"keep numbers as they are, and reply with only the translation:\n\n{text}"
            ),
        )
        return (resp.text or "").strip() or None
    except Exception as exc:
        log.warning("Gemini translate failed: %s", exc)
        return None
