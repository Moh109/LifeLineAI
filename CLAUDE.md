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
python scripts\fake_call.py --spanish --phone +15550000199
python scripts\fake_call.py --repeat --phone +15550000199
```

## Production (deployed Oct 11)
- **https://lifeline-ai.us** (domain from Porkbun, A records for @ and www -> 108.61.222.88). The same server also
  answers on https://108.61.222.88.sslip.io, which the ElevenLabs tools and webhook still use (Vultr, Ubuntu 24.04, Dallas). App in `/opt/lifeline`, systemd service `lifeline`,
  Caddy for HTTPS (Let's Encrypt). Same Tiger Data DB as local, so local and prod see the same cases.
- SSH: `ssh -i ~/.ssh/lifeline_vultr root@108.61.222.88` (key made for this project, no passphrase).
- Ship code: push to GitHub, then on the server `cd /opt/lifeline && git pull && sudo bash deploy/setup_vultr.sh "lifeline-ai.us, www.lifeline-ai.us, 108.61.222.88.sslip.io"`.
  ALWAYS pass all three names in quotes: the script rewrites the Caddy config, and leaving one out takes that
  address offline (drop sslip.io and every ElevenLabs tool call and webhook fails).
- Change secrets: edit local `backend/.env`, then
  `scp -i ~/.ssh/lifeline_vultr backend/.env root@108.61.222.88:/opt/lifeline/backend/.env` and `systemctl restart lifeline`
  (and `chmod 600` the file). Never paste .env into chat.
- Logs: `ssh ... 'journalctl -u lifeline -n 100 --no-pager'`.
- ElevenLabs: all 3 intake tools + post-call webhook point at prod. The webhook URL can't be edited via API
  (PATCH ignores it), so the prod webhook is a new one, "intake-server" (id 99afcd38...). The old tunnel webhook
  "intake" (70510ef4...) is no longer attached to the agent.

- Callbacks ON (Oct 11): agent "Lifeline Callback" + tool update_from_callback created via API, pointing at prod.
  CALLBACK_AGENT_ID and CALLBACK_ALLOW_OVERRIDES=true in .env. Callback checkbox defaults off for Delayed cases.

## Known gotchas
- Values in `backend/.env` must NOT be quoted: `fake_call.py` doesn't strip quotes, so the secret won't match (401).
- Gemini free tier = ~20 requests/day PER MODEL (429 RESOURCE_EXHAUSTED when used up, resets ~24h later).
  `gemini-3.8-flash` ran out Oct 10. Using `gemini-3.5-flash-lite` (~3s vs ~85s for Flash). Backups with
  fresh quota: `gemini-3.7-flash`, `gemini-3.5-flash`. Enabling billing in AI Studio removes the limit.
- Backboard API paths in `memory.py` are unverified; failures are caught and non-fatal.
- Only `+1555…` numbers count as fake. Other test numbers will get real callback attempts once callbacks are configured.
- Dashboard/API has no login: don't share the public URL; `/api/demo/reset?all=true` wipes everything.
- Campus Wi-Fi blocks QUIC: run the tunnel with `--protocol http2`
  (`& 'C:\Program Files (x86)\cloudflared\cloudflared.exe' tunnel --protocol http2 --url http://localhost:8000`).
  Quick-tunnel URL changes on every restart -> update all ElevenLabs tool URLs + post-call webhook.
- In ElevenLabs, `caller_phone` is set to Required: OFF on every tool (browser/web calls have no caller ID).
- ElevenLabs fires tools in parallel; `cases._case_lock` prevents duplicate cases. Don't remove it.
- If the agent *says* it flagged/saved but no `tool /tools/...` line is in the backend log, the tool
  isn't attached/published in ElevenLabs. Calls that end with no case log their transcript.
- The ElevenLabs tester always uses the same caller ID, so later test calls merge into its open case
  (repeat-caller logic). Clear test cases before a clean test or the demo.
- Midnight checkpoint PASSED Oct 10 21:38 (browser call -> live case LF-1619, pin, transcript).
