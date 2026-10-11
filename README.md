# Lifeline

When disaster floods the 911 lines, Lifeline answers instead of hold music. A voice agent talks to the caller in their language, gets the rescue details, ranks them on a live map by danger, and calls them back when a team is assigned. Human dispatchers make every decision.

Built for CodeRED Orion, October 2026.

```
Caller's phone ─▶ Twilio number ─▶ ElevenLabs intake agent ──tools──▶ Backend (FastAPI)
                                                                       │  scores, saves, pushes
       ◀── callback with ETA ── ElevenLabs callback agent ◀── assign ──┤
                                                                       ├─▶ Tiger Data (cases + call events)
                                Dispatcher dashboard ◀── live updates ─┤─▶ Gemini (translate, summarize, fill gaps)
                                                                       └─▶ Backboard (remembers callers)
```

## What's in here

| Path | What it is |
| --- | --- |
| `agent/intake_agent_prompt.md` | First message, system prompt and settings for the intake agent |
| `agent/callback_agent_prompt.md` | Same for the callback agent |
| `agent/tools.md` | Every tool to add in ElevenLabs, field by field, plus the post-call webhook |
| `backend/` | FastAPI app: agent tools, webhook, scoring, Gemini, Backboard, callbacks, surge simulator |
| `frontend/` | Dispatcher dashboard (React + Leaflet) |
| `scripts/fake_call.py` | Pretends to be ElevenLabs, so you can test without a phone |
| `deploy/` | One-command Vultr setup with HTTPS on your domain |

---

## Build order

Do the steps in order. Each one ends with a check. Don't move on until it passes.

### Step 0: Accounts and keys (everyone, 20 min)

| Who | Get | Where |
| --- | --- | --- |
| Voice | ElevenLabs account + API key | elevenlabs.io → profile → API keys |
| Voice | Twilio account + a phone number | twilio.com. **Upgrading (about $20) is required, not optional:** trial accounts only allow verified numbers and strip `<Stream>`, which ElevenLabs needs. See Step 2 |
| Backend | Gemini API key | aistudio.google.com → Get API key |
| Backend | Tiger Data service | tigerdata.com → create a service → copy the connection string. Ask at the MLH table for credits |
| Infra | Vultr account + credits | MLH table / vultr.com |
| Infra | Domain | MLH's GoDaddy Registry offer |
| Infra | Backboard API key | app.backboard.io → Settings → API keys |

Put every key in the team's private chat, never in GitHub.

### Step 1: Talk to the agent in your browser (Voice, 15 min)

1. ElevenLabs → Agents → **Create agent** → blank. Name it `Lifeline Intake`.
2. Paste the first message and system prompt from `agent/intake_agent_prompt.md`.
3. Apply the settings table at the bottom of that file (voice, multilingual model, extra languages, End call and Language detection tools).
4. Click **Test AI agent** and pretend you're trapped. Try Spanish halfway through.

**Check:** it asks one question at a time, switches language, and reads back your address. The tools aren't connected yet, so it may say it can't submit. That's fine.

### Step 2: Real phone call (Voice, 20 min)

> **A Twilio trial account will not work. Upgrade first.** Trial accounts only allow verified numbers, and they strip the `<Stream>` instruction that ElevenLabs uses to carry the call audio, so the agent never hears the caller. Upgrade in the Twilio console (Billing → Upgrade, about $20 of credit) *before* buying the number.
>
> Money plan: everything else (Steps 3 to 5, the browser tester, `fake_call.py`, the cloudflared tunnel) is free. Pay only after a browser test call creates a case on the dashboard end to end. If that never works, use the free ElevenLabs web call (QR code to a call page) instead of a phone number, and skip this step.

1. Twilio: upgrade the account, then buy a local number (713, 832 or 281 area code if available).
2. ElevenLabs → **Phone numbers** → **Import number** → From Twilio. Enter the number, Account SID and Auth Token from the Twilio console.
3. Assign `Lifeline Intake` to the number.
4. Call it from your phone.

**Check:** you're talking to the agent on a real phone call. This is the riskiest step of the whole project. If it fails, keep going with the browser test and fix it in parallel.

### Step 3: Run the backend (Backend, 15 min)

```bash
cd backend
cp .env.example .env          # then fill in DATABASE_URL, TOOL_SECRET, GEMINI_API_KEY
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

`TOOL_SECRET` is any long random string you make up.

**Check:** http://localhost:8000/api/health shows `"ok": true`. With a Tiger Data URL it also shows `"timescale": true`.

### Step 4: Run the dashboard (Frontend, 10 min)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. In another terminal, from the project root:

```bash
python scripts/fake_call.py --critical
python scripts/fake_call.py --spanish --phone +18325550199
python scripts/fake_call.py --repeat --phone +18325550199
```

**Check:** cases appear live, the critical one pops an alert, and the repeat caller shows "called 2x". Click **Run Harvey surge** and watch 300 calls fill the map.

### Step 5: Connect the agent to the backend (Voice + Backend, 30 min)

ElevenLabs has to reach your laptop, so open a public tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
# Install: Windows: winget install Cloudflare.cloudflared   Mac: brew install cloudflared
```

It prints a URL like `https://something.trycloudflare.com`. That's `YOUR_PUBLIC_URL` until you deploy.

1. Add the three intake tools exactly as in `agent/tools.md`. The URL is `YOUR_PUBLIC_URL/tools/<name>` and the header is `X-Lifeline-Secret`.
2. Add the post-call webhook (bottom of `agent/tools.md`). Put its HMAC secret in `ELEVENLABS_WEBHOOK_SECRET` and restart the backend.

**Check:** call the number. The case appears on the dashboard while you're still on the phone, and the transcript shows up a few seconds after you hang up. Backend logs print every tool call (`tool /tools/... <-`), which is the first place to look when something's off.

### Step 6: Callbacks (Voice, 20 min)

1. Create a second agent `Lifeline Callback` from `agent/callback_agent_prompt.md`. Add its `update_from_callback` tool.
2. Fill in `.env`:
   - `ELEVENLABS_API_KEY`
   - `CALLBACK_AGENT_ID` (on the agent's page)
   - `INTAKE_AGENT_ID`
   - `ELEVENLABS_PHONE_NUMBER_ID`: the ID of the imported number, not the number itself. Find it with:
     ```bash
     curl -s -H "xi-api-key: YOUR_KEY" https://api.elevenlabs.io/v1/convai/phone-numbers
     ```
3. If you turned on First message and Language overrides in the callback agent's Security tab, set `CALLBACK_ALLOW_OVERRIDES=true`.
4. Restart the backend.

**Check:** call in, open your case on the dashboard, click **Assign and call back**. Your phone rings with the ETA. This needs the upgraded Twilio account from Step 2; a trial account cannot place it.

### Step 7: Gemini and Backboard (Backend, 15 min)

- `GEMINI_API_KEY` turns on post-call translation and summaries, dropped-call recovery, and **Add from a post**. If the default model name errors, pick a current Flash model in AI Studio and set `GEMINI_MODEL`.
- `BACKBOARD_API_KEY` turns on caller memory. On first start the backend creates an assistant and logs `BACKBOARD_ASSISTANT_ID=...`. Paste that into `.env` so memory survives restarts.

**Check:** a Spanish call shows a **Show English** toggle on the transcript. A repeat caller's case shows **Earlier from this number**.

### Step 8: Deploy (Infra, 30 min, by midnight)

1. Vultr: Cloud Compute, Ubuntu 24.04, 2 GB RAM, a region near Dallas.
2. At your domain registrar, add an **A record** for the domain pointing to the server's IP.
3. On the server:
   ```bash
   git clone <your repo> /opt/lifeline
   cd /opt/lifeline/backend && cp .env.example .env && nano .env   # paste the real values
   sudo bash /opt/lifeline/deploy/setup_vultr.sh yourdomain.tech
   ```
4. In ElevenLabs, change every tool URL and the post-call webhook from the tunnel to `https://yourdomain.tech`.

**Check:** `https://yourdomain.tech` shows the dashboard and a phone call lands on it. To ship code changes later, `git pull` and re-run the same script.

---

## Demo checklist

- [ ] Phone number printed big on a card for judges to call
- [ ] Twilio account upgraded (not trial) and a teammate's phone ready as a backup caller
- [ ] Clear old test cases: `curl -X POST "https://yourdomain.tech/api/demo/reset?all=true"`
- [ ] Dashboard open full screen. Close the queue detail before judges arrive
- [ ] One rehearsed flow: judge calls → pin drops → open case → **Assign and call back** → judge's phone rings → **Run Harvey surge**
- [ ] Backup video recorded by 11 am
- [ ] Phone hotspot ready in case the venue Wi-Fi dies

## When something breaks

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Agent says it can't save the request | Tool URL wrong, tunnel died, or secret mismatch | Look for `tool /tools/...` in backend logs. No line means ElevenLabs never reached you. A 401 means the `X-Lifeline-Secret` value is wrong |
| Case appears but no pin | Address didn't geocode | The card says "not on map". Open it and click **Place pin by hand**. For better matching, set `GOOGLE_MAPS_API_KEY` |
| Pin is in the right area but not the exact house | Street not found, neighborhood was | Dashed pin outline means approximate. Drag to fix |
| No transcript after the call | Post-call webhook not set, or a signature mismatch (401 in logs) | Re-copy the HMAC secret into `ELEVENLABS_WEBHOOK_SECRET` and restart |
| Phone call plays a Twilio trial message, gets rejected, or connects but the agent never hears you | Twilio account is still a trial | Upgrade the Twilio account (Step 2). The browser tester working while the phone doesn't is the giveaway |
| Callback status says `failed: ...` | The error text says why | Usually the Twilio account is still a trial (upgrade it, see Step 2), or a wrong `ELEVENLABS_PHONE_NUMBER_ID` |
| Callback checkbox greyed out | Callback env vars missing, or a simulated caller | Fill the Step 6 values. Simulated cases never call anyone |
| Phone number shows as empty in cases | The `caller_phone` parameter isn't set to the `system__caller_id` dynamic variable | See `agent/tools.md`. The agent also asks for a callback number as a fallback |
| "Add from a post" disabled | No Gemini key | Set `GEMINI_API_KEY` |
| Dashboard says Reconnecting | Backend down | `journalctl -u lifeline -f` on the server |

## How priority works

Gemini and the voice agent only pull out facts. The score is plain rules in `backend/app/scoring.py`, so it's the same every time and every point shows on the case:

| Factor | Points |
| --- | --- |
| Water level: roof 40, chest 32, waist 24, knee 12, ankle 5, unknown 10 | 0 to 40 |
| Life-threatening (also forces at least 70) | +30 |
| Water rising | +10 |
| Depends on medicine or power (oxygen, dialysis, insulin...) | +15 |
| Injury | +10 |
| Each vulnerable group (elderly, baby or child, disabled, pregnant) | +8, max 16 |
| People on site | +2 each, max 10 |
| Phone battery 15% or less | +5 |
| Waiting time, while unassigned | +1 per 10 min, max 20 |

60 and up is **Immediate** (red), 35 to 59 **Urgent** (orange), under 35 **Delayed** (olive).

## Where each sponsor's tech does real work

| Prize | Where |
| --- | --- |
| ElevenLabs | Two agents, live inbound and outbound phone calls, multilingual, four server tools |
| Gemini | Post-call translation and summary, filling gaps the agent missed, rebuilding dropped calls, turning social posts into cases |
| Backboard | Remembers every caller across calls; shown in the agent's repeat-caller greeting and on the case |
| Tiger Data | `call_events` hypertable, a real-time continuous aggregate `calls_per_minute`, live surge chart from `time_bucket` |
| Vultr + GoDaddy Registry | Production host with HTTPS on the team domain |

## API

| Method | Path | Used by |
| --- | --- | --- |
| POST | `/tools/lookup_caller`, `/tools/flag_critical`, `/tools/submit_rescue_request`, `/tools/update_from_callback` | ElevenLabs agents |
| POST | `/webhooks/elevenlabs` | ElevenLabs post-call webhook |
| GET | `/api/cases`, `/api/cases/{id}`, `/api/stats`, `/api/health` | Dashboard |
| POST | `/api/cases/{id}/assign`, `/status`, `/location`, `/callback` | Dashboard |
| POST | `/api/intake/text` | Add from a post |
| POST | `/api/demo/surge`, `/api/demo/reset` | Demo controls |
| WS | `/ws` | Live updates |

The dashboard and its API have no login. That's fine for the demo, but say it before the judges ask: a real deployment puts dispatchers behind the county's single sign-on.
