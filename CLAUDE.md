# Lifeline — context for Claude sessions

AI rescue line for when 911 is overloaded during a flood. Built at CodeRED Orion (University of Houston).
**Hard deadline: submit by Sun Oct 11, 12:30 PM CT** (hacking ends 1:00 PM). 4-person team.

## How it works (one call)
Caller → Twilio number → ElevenLabs intake agent → webhook tools on our FastAPI backend
(`/tools/lookup_caller`, `/tools/flag_critical`, `/tools/submit_rescue_request`) → case scored by rules
(`backend/app/scoring.py`), saved to Postgres (Tiger Data), pushed to the React dashboard over `/ws`.
After the call, ElevenLabs posts the transcript to `/webhooks/elevenlabs`; Gemini translates/summarizes.
Dispatcher clicks **Assign and call back** → backend starts an ElevenLabs outbound call (callback agent)
with the ETA; that agent can call `/tools/update_from_callback`.

## Layout
- `README.md` — the build guide, step by step, each step ends with a check. Follow it in order.
- `agent/` — ElevenLabs prompts and tool definitions (pasted into the ElevenLabs UI, not code).
- `backend/app/` — FastAPI. Start with `main.py` (routes) and `cases.py` (case logic).
- `frontend/src/` — React + Leaflet dashboard. Start with `App.jsx`. Vite proxies `/api` and `/ws` to :8000.
- `scripts/fake_call.py` — pretends to be ElevenLabs (tool calls + webhook) so we can test without a phone.
- `deploy/` — Vultr + Caddy setup.

## Rules
- **Help run it, connect real services, fix what breaks. Do NOT redesign.** Small, focused changes.
  Don't rewrite working code. Explain what you're doing in simple words.
- **OS is Windows.** Give PowerShell commands (e.g. `.venv\Scripts\Activate.ps1`, `Copy-Item`).
- **Never print, log or commit secrets.** `backend/.env` stays out of git. Don't `cat` the .env file.
- Ask before installing anything globally or deleting files.
- Git: this project has its own repo in this folder. The user's home folder (`C:\Users\shaik`) is
  ALSO a git repo — never run git commands that target it.
- **45-minute rule:** if a fix will take more than ~45 minutes, say so and propose a simpler fallback.

## Money plan
- Build and test everything for free first: `fake_call.py`, the ElevenLabs browser tester, cloudflared tunnel.
- Stay free unless it's really required. Only pay for Twilio (~$20) and maybe ElevenLabs Starter ($6)
  **after the midnight checkpoint**: a browser call to the agent creates a case on the dashboard end to end.
- If that checkpoint fails, the fallback is a free QR-code web call (ElevenLabs web widget) instead of a phone number.
- Twilio upgrade is REQUIRED for the phone path: trial accounts only allow verified numbers and strip
  `<Stream>`, which ElevenLabs needs.

## Running locally (Windows / PowerShell)
```powershell
# backend (from backend\)
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000     # check http://localhost:8000/api/health

# dashboard (from frontend\)
npm run dev                                   # http://localhost:5173

# fake calls (from project root, backend venv active)
python scripts\fake_call.py --critical
python scripts\fake_call.py --spanish --phone +18325550199
python scripts\fake_call.py --repeat --phone +18325550199
```

## Known gotchas
- Values in `backend/.env` must NOT be quoted: `fake_call.py` doesn't strip quotes, so the secret won't match (401).
- `GEMINI_MODEL` default may not be a real model name; if Gemini calls fail, set a current Flash model.
- Backboard API paths in `memory.py` are unverified; failures are caught and non-fatal.
- Only `+1555…` numbers count as fake. Other test numbers will get real callback attempts once callbacks are configured.
- Dashboard/API has no login: don't share the public URL; `/api/demo/reset?all=true` wipes everything.
