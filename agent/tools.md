# Agent tools

Every tool is a **Webhook** tool: ElevenLabs → Agent → Tools → Add tool → Webhook.

For all of them:

- **Method:** `POST`
- **URL:** `https://YOUR_PUBLIC_URL/tools/<tool name>`. While developing, `YOUR_PUBLIC_URL` is your cloudflared tunnel. After deploy, it's your domain.
- **Content type:** JSON
- **Header:** `X-Lifeline-Secret` = the same value as `TOOL_SECRET` in `.env`. Store it as an ElevenLabs **Secret**.
- **Response timeout:** 10 seconds

Each body parameter has a **value type**:

- **Dynamic variable:** ElevenLabs fills it in automatically. Pick the variable named in the table.
- **LLM prompt:** the agent fills it in from the conversation. Paste the description exactly; the agent reads it to decide what to send.

If your dashboard doesn't offer "Dynamic variable" for a body parameter, make it **LLM prompt** with the description `Always send exactly: {{system__caller_id}}` (or the matching variable). The backend copes either way.

---

## Intake agent

### 1. `lookup_caller`

**Description:** `Call this first, before asking anything else, to check whether this caller already has an open rescue request.`

| Identifier | Type | Required | Value type | Description / variable |
| --- | --- | --- | --- | --- |
| `caller_phone` | string | yes | Dynamic variable | `system__caller_id` |
| `conversation_id` | string | no | Dynamic variable | `system__conversation_id` |

Returns `known`, `case_number_spoken`, `caller_name`, `address`, `status`, `unit`, `eta_minutes`, `history`, `say`.

### 2. `flag_critical`

**Description:** `Call immediately when anyone is not breathing, unconscious, bleeding heavily, or trapped in water over their head. Alerts a human dispatcher right away. Then keep collecting details.`

| Identifier | Type | Required | Value type | Description / variable |
| --- | --- | --- | --- | --- |
| `caller_phone` | string | yes | Dynamic variable | `system__caller_id` |
| `conversation_id` | string | no | Dynamic variable | `system__conversation_id` |
| `reason` | string | yes | LLM prompt | `One short line describing the life threat, in English.` |
| `address` | string | no | LLM prompt | `The location if you already have it, otherwise leave empty.` |
| `callback_number` | string | no | LLM prompt | `A callback number the caller gave, if different from caller ID.` |

### 3. `submit_rescue_request`

**Description:** `Submit or update the rescue request once you have the location (and anything else you know). Call it again whenever the caller gives new or changed details.`

| Identifier | Type | Required | Value type | Description / variable |
| --- | --- | --- | --- | --- |
| `caller_phone` | string | yes | Dynamic variable | `system__caller_id` |
| `conversation_id` | string | no | Dynamic variable | `system__conversation_id` |
| `address` | string | yes | LLM prompt | `Street address or cross streets, plus city if given, exactly as confirmed with the caller.` |
| `landmark` | string | no | LLM prompt | `Nearby landmark such as apartment complex, store, church, school.` |
| `caller_name` | string | no | LLM prompt | `Caller's name.` |
| `callback_number` | string | no | LLM prompt | `Callback number if different from caller ID.` |
| `language` | string | no | LLM prompt | `Language you are speaking with the caller, e.g. English, Spanish, Vietnamese.` |
| `people_count` | integer | no | LLM prompt | `Number of people at the location including the caller.` |
| `water_level` | string | no | LLM prompt | `One of: none, ankle, knee, waist, chest, roof, unknown.` |
| `water_rising` | boolean | no | LLM prompt | `True if the caller says the water is rising.` |
| `vulnerable` | string | no | LLM prompt | `Comma-separated: elderly, baby, child, pregnant, disabled. Empty if none.` |
| `medical_needs` | string | no | LLM prompt | `Comma-separated needs such as insulin, oxygen, dialysis, ventilator, medication. Empty if none.` |
| `injuries` | string | no | LLM prompt | `Short description of any injuries. Empty if none.` |
| `life_threatening` | boolean | no | LLM prompt | `True if anyone is not breathing, unconscious, bleeding heavily, or in water over their head.` |
| `battery_pct` | integer | no | LLM prompt | `Phone battery percent if the caller said it.` |
| `pets` | string | no | LLM prompt | `Pets at the location, e.g. 2 dogs. Empty if none.` |
| `notes` | string | no | LLM prompt | `Anything else a rescue team should know, in English.` |

Returns `case_number`, `case_number_spoken`, `priority_label`, `say`.

---

## Callback agent

### 4. `update_from_callback`

**Description:** `Update the case when the caller moved, something changed, or they say they are already safe.`

| Identifier | Type | Required | Value type | Description / variable |
| --- | --- | --- | --- | --- |
| `case_id` | string | yes | Dynamic variable | `case_id` (the backend passes it when starting the call) |
| `status` | string | no | LLM prompt | `"safe" if they were already rescued or are safe, otherwise "still_waiting".` |
| `new_address` | string | no | LLM prompt | `New confirmed location if they moved. Empty otherwise.` |
| `water_level` | string | no | LLM prompt | `One of: none, ankle, knee, waist, chest, roof, unknown. Only if it changed.` |
| `water_rising` | boolean | no | LLM prompt | `True if the water is still rising.` |
| `injuries` | string | no | LLM prompt | `New injuries, if any.` |
| `life_threatening` | boolean | no | LLM prompt | `True if someone is now not breathing, unconscious, or bleeding heavily.` |
| `notes` | string | no | LLM prompt | `Anything else that changed, in English.` |

---

## Post-call webhook (both agents)

ElevenLabs → Agents → **Settings** → Post-call webhook:

- URL: `https://YOUR_PUBLIC_URL/webhooks/elevenlabs`
- Turn on **transcription** events. Leave audio off.
- Copy the **HMAC secret** it shows into `ELEVENLABS_WEBHOOK_SECRET` in `.env`.

After each call, the backend attaches the transcript to the case. Gemini then translates it, writes the English summary, and fills in anything the agent missed. If a call drops before `submit_rescue_request`, Gemini rebuilds the request from the transcript, so no caller is lost.
