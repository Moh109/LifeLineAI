import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _bool(name: str, default: bool = False) -> bool:
    value = _get(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


DATABASE_URL = _get("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/lifeline")

ELEVENLABS_API_KEY = _get("ELEVENLABS_API_KEY")
INTAKE_AGENT_ID = _get("INTAKE_AGENT_ID")
CALLBACK_AGENT_ID = _get("CALLBACK_AGENT_ID")
ELEVENLABS_PHONE_NUMBER_ID = _get("ELEVENLABS_PHONE_NUMBER_ID")
ELEVENLABS_WEBHOOK_SECRET = _get("ELEVENLABS_WEBHOOK_SECRET")
CALLBACK_ALLOW_OVERRIDES = _bool("CALLBACK_ALLOW_OVERRIDES")
TOOL_SECRET = _get("TOOL_SECRET")

GEMINI_API_KEY = _get("GEMINI_API_KEY")
# Several keys (comma-separated) so one key's free quota running out doesn't stop Gemini. Falls back to GEMINI_API_KEY.
GEMINI_API_KEYS = [k.strip() for k in _get("GEMINI_API_KEYS").split(",") if k.strip()] or \
    ([GEMINI_API_KEY] if GEMINI_API_KEY else [])
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-3.5-flash-lite")
# Tried (with every key) only after GEMINI_MODEL is out of quota on all keys
GEMINI_BACKUP_MODEL = _get("GEMINI_BACKUP_MODEL", "gemini-3.5-flash")

BACKBOARD_API_KEY = _get("BACKBOARD_API_KEY")
BACKBOARD_ASSISTANT_ID = _get("BACKBOARD_ASSISTANT_ID")

GOOGLE_MAPS_API_KEY = _get("GOOGLE_MAPS_API_KEY")
GEOCODER_CONTACT_EMAIL = _get("GEOCODER_CONTACT_EMAIL", "+https://github.com/Moh109/LifeLineAI")

PORT = int(_get("PORT", "8000"))
# /docs, /redoc and /openapi.json: off unless API_DOCS=true (only turn on for local development)
API_DOCS = _bool("API_DOCS")
CORS_ORIGINS = [o.strip() for o in _get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"


def feature_flags() -> dict:
    return {
        "gemini": bool(GEMINI_API_KEYS),
        "gemini_keys": len(GEMINI_API_KEYS),
        "elevenlabs_callback": bool(ELEVENLABS_API_KEY and CALLBACK_AGENT_ID and ELEVENLABS_PHONE_NUMBER_ID),
        "webhook_signature": bool(ELEVENLABS_WEBHOOK_SECRET),
        "tool_secret": bool(TOOL_SECRET),
        "backboard": bool(BACKBOARD_API_KEY),
        "geocoder": "google" if GOOGLE_MAPS_API_KEY else "openstreetmap",
    }
