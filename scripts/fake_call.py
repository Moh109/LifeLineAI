"""Pretend to be ElevenLabs: run one call's worth of tool calls + the post-call webhook.

Lets the backend and dashboard people work without a phone.

    python scripts/fake_call.py                      # English caller
    python scripts/fake_call.py --spanish            # Spanish caller
    python scripts/fake_call.py --critical           # life-threatening path
    python scripts/fake_call.py --repeat             # same number calls again with an update
    python scripts/fake_call.py --url https://your-tunnel.trycloudflare.com

Reads TOOL_SECRET and ELEVENLABS_WEBHOOK_SECRET from backend/.env if present.
"""

import argparse
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path

import httpx

env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8000")
parser.add_argument("--phone", default="+15550000142")  # +1555 = fake, never called back
parser.add_argument("--spanish", action="store_true")
parser.add_argument("--critical", action="store_true")
parser.add_argument("--repeat", action="store_true")
args = parser.parse_args()

TOOL_HEADERS = {"X-Lifeline-Secret": os.getenv("TOOL_SECRET", "")}
conversation_id = f"conv_fake_{uuid.uuid4().hex[:10]}"
client = httpx.Client(base_url=args.url, timeout=30)


def tool(name: str, body: dict) -> dict:
    body = {"caller_phone": args.phone, "conversation_id": conversation_id, **body}
    r = client.post(f"/tools/{name}", json=body, headers=TOOL_HEADERS)
    r.raise_for_status()
    print(f"\n-> {name}\n<- {json.dumps(r.json(), indent=2, ensure_ascii=False)}")
    return r.json()


def webhook(transcript: list[tuple[str, str]]) -> None:
    payload = {
        "type": "post_call_transcription",
        "event_timestamp": int(time.time()),
        "data": {
            "agent_id": os.getenv("INTAKE_AGENT_ID", "agent_fake"),
            "conversation_id": conversation_id,
            "status": "done",
            "transcript": [{"role": r, "message": m, "time_in_call_secs": i * 5} for i, (r, m) in enumerate(transcript)],
            "metadata": {"call_duration_secs": len(transcript) * 6},
            "analysis": {"transcript_summary": ""},
            "conversation_initiation_client_data": {"dynamic_variables": {"system__caller_id": args.phone}},
        },
    }
    raw = json.dumps(payload)
    headers = {"Content-Type": "application/json"}
    secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET")
    if secret:
        t = str(int(time.time()))
        sig = hmac.new(secret.encode(), f"{t}.{raw}".encode(), hashlib.sha256).hexdigest()
        headers["ElevenLabs-Signature"] = f"t={t},v0={sig}"
    r = client.post("/webhooks/elevenlabs", content=raw, headers=headers)
    print(f"\n-> post-call webhook: {r.status_code} {r.text}")


tool("lookup_caller", {})

if args.repeat:
    tool("submit_rescue_request", {"water_level": "chest", "water_rising": True,
                                   "notes": "Second call: water rose from waist to chest"})
    webhook([("agent", "Lifeline emergency line..."), ("user", "It's me again, the water is at my chest now.")])
elif args.spanish:
    if args.critical:
        tool("flag_critical", {"reason": "Elderly man unconscious", "address": "8810 Jason St"})
    tool("submit_rescue_request", {
        "address": "8810 Jason St, Houston", "landmark": "near Meyerland Plaza", "caller_name": "María López",
        "language": "Spanish", "people_count": 4, "water_level": "waist", "water_rising": True,
        "vulnerable": "elderly, baby", "medical_needs": "insulin", "battery_pct": 18,
    })
    webhook([
        ("agent", "Línea de emergencia Lifeline. ¿Hay alguien en peligro ahora mismo?"),
        ("user", "Sí, estamos atrapados. Mi papá tiene diabetes y necesita su insulina. El agua nos llega a la cintura."),
        ("agent", "¿Cuál es su dirección?"),
        ("user", "8810 Jason Street, cerca de Meyerland Plaza. Somos cuatro, con mi bebé."),
    ])
else:
    if args.critical:
        tool("flag_critical", {"reason": "Woman not breathing after being pulled from water", "address": "2500 Lyons Ave"})
    tool("submit_rescue_request", {
        "address": "2500 Lyons Ave, Houston", "caller_name": "James Carter", "language": "English",
        "people_count": 3, "water_level": "chest", "water_rising": True, "vulnerable": "elderly",
        "medical_needs": "oxygen", "battery_pct": 40, "pets": "1 dog",
    })
    webhook([
        ("agent", "Lifeline emergency line. Are you or anyone with you in danger right now?"),
        ("user", "The water's at my chest and rising. My grandmother is on oxygen and the power's out."),
        ("agent", "What's your address?"),
        ("user", "2500 Lyons Avenue in Fifth Ward. Three of us and our dog."),
    ])

print(f"\nDone. Conversation id: {conversation_id}. Check the dashboard.")
