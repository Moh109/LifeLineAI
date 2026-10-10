"""ElevenLabs: outbound callbacks and post-call webhook verification."""

import hashlib
import hmac
import logging
import time

import httpx

from . import config

log = logging.getLogger("lifeline.elevenlabs")

OUTBOUND_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"

# ElevenLabs agent language codes for the languages the dashboard knows about
LANGUAGE_CODES = {
    "english": "en", "spanish": "es", "vietnamese": "vi", "chinese": "zh", "mandarin": "zh",
    "arabic": "ar", "hindi": "hi", "french": "fr", "portuguese": "pt", "korean": "ko",
    "tagalog": "fil", "filipino": "fil", "russian": "ru", "german": "de",
}


def language_code(language: str | None) -> str | None:
    if not language:
        return None
    return LANGUAGE_CODES.get(language.strip().lower())


def callback_ready() -> bool:
    return bool(config.ELEVENLABS_API_KEY and config.CALLBACK_AGENT_ID and config.ELEVENLABS_PHONE_NUMBER_ID)


async def start_outbound_call(to_number: str, dynamic_variables: dict, first_message: str | None = None,
                              language: str | None = None) -> dict:
    """Start a callback. Returns {'ok': bool, 'conversation_id'?, 'error'?}."""
    if not callback_ready():
        return {"ok": False, "error": "Callback not configured (ELEVENLABS_API_KEY, CALLBACK_AGENT_ID, ELEVENLABS_PHONE_NUMBER_ID)"}

    client_data: dict = {"dynamic_variables": {k: ("" if v is None else v) for k, v in dynamic_variables.items()}}
    if config.CALLBACK_ALLOW_OVERRIDES:
        agent_override: dict = {}
        if first_message:
            agent_override["first_message"] = first_message
        code = language_code(language)
        if code and code != "en":
            agent_override["language"] = code
        if agent_override:
            client_data["conversation_config_override"] = {"agent": agent_override}

    body = {
        "agent_id": config.CALLBACK_AGENT_ID,
        "agent_phone_number_id": config.ELEVENLABS_PHONE_NUMBER_ID,
        "to_number": to_number,
        "conversation_initiation_client_data": client_data,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(OUTBOUND_URL, json=body, headers={"xi-api-key": config.ELEVENLABS_API_KEY})
        data = r.json() if r.content else {}
        if r.status_code >= 400 or data.get("success") is False:
            msg = data.get("detail") or data.get("message") or r.text
            log.error("Outbound call failed (%s): %s", r.status_code, msg)
            return {"ok": False, "error": str(msg)[:300]}
        return {"ok": True, "conversation_id": data.get("conversation_id"), "call_sid": data.get("callSid")}
    except Exception as exc:
        log.error("Outbound call error: %s", exc)
        return {"ok": False, "error": str(exc)[:300]}


def verify_webhook(body: bytes, signature_header: str | None, tolerance_s: int = 1800) -> bool:
    """Check the ElevenLabs-Signature header: 't=<unix>,v0=<hex hmac_sha256(secret, f'{t}.{body}')>'."""
    secret = config.ELEVENLABS_WEBHOOK_SECRET
    if not secret:
        return True  # signature checking off (dev)
    if not signature_header:
        return False
    parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
    timestamp, sent = parts.get("t"), parts.get("v0")
    if not timestamp or not sent:
        return False
    try:
        if abs(time.time() - int(timestamp)) > tolerance_s:
            return False
    except ValueError:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.{body.decode('utf-8')}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sent)
