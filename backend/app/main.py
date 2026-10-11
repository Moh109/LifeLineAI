"""Lifeline API: voice-agent tools, ElevenLabs webhook, dispatcher API, live updates."""

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import cases, config, db, elevenlabs, gemini, memory, simulator
from .realtime import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lifeline")


async def _stats_loop() -> None:
    while True:
        await asyncio.sleep(3)
        if hub.clients:
            try:
                await hub.broadcast({"type": "stats", "stats": await db.stats()})
            except Exception as exc:
                log.debug("stats broadcast failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    if memory.enabled():
        await memory.ensure_assistant()
    task = asyncio.create_task(_stats_loop())
    log.info("Features: %s", config.feature_flags())
    yield
    task.cancel()
    await db.close()


_docs = config.API_DOCS
app = FastAPI(title="Lifeline", lifespan=lifespan, docs_url="/docs" if _docs else None,
              redoc_url="/redoc" if _docs else None, openapi_url="/openapi.json" if _docs else None)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# ---------- voice agent tools (called by ElevenLabs during a call) ----------

def require_tool_secret(x_lifeline_secret: str | None = Header(default=None)) -> None:
    if config.TOOL_SECRET and x_lifeline_secret != config.TOOL_SECRET:
        raise HTTPException(status_code=401, detail="bad tool secret")


def _dispatch_key_ok(key: str | None) -> bool:
    return not config.DISPATCH_KEY or hmac.compare_digest(key or "", config.DISPATCH_KEY)


def require_dispatch_key(x_dispatch_key: str | None = Header(default=None)) -> None:
    """Dashboard routes: the browser sends the key the dispatcher typed in (X-Dispatch-Key)."""
    if not _dispatch_key_ok(x_dispatch_key):
        raise HTTPException(status_code=401, detail="dispatch key required")


def require_dispatch_key_or_query(x_dispatch_key: str | None = Header(default=None), key: str | None = None) -> None:
    """Like require_dispatch_key, but also takes ?key= (an <audio src> can't send headers; /ws does the same)."""
    if not (_dispatch_key_ok(x_dispatch_key) if x_dispatch_key else _dispatch_key_ok(key)):
        raise HTTPException(status_code=401, detail="dispatch key required")


async def _tool_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}
    log.info("tool %s <- %s", request.url.path, json.dumps(body)[:600])
    return body if isinstance(body, dict) else {}


def _ids(body: dict) -> tuple[str | None, str | None]:
    phone = cases.normalize_phone(body.get("caller_phone")) or cases.normalize_phone(body.get("callback_number"))
    conv = cases.clean_str(body.get("conversation_id"))
    if conv and "{{" in conv:
        conv = None
    return phone, conv


@app.post("/tools/lookup_caller", dependencies=[Depends(require_tool_secret)])
async def tool_lookup_caller(request: Request):
    body = await _tool_body(request)
    phone, conv = _ids(body)
    return await cases.lookup(phone, conv)


@app.post("/tools/flag_critical", dependencies=[Depends(require_tool_secret)])
async def tool_flag_critical(request: Request):
    body = await _tool_body(request)
    phone, conv = _ids(body)
    case = await cases.flag_critical(body, phone=phone, conversation_id=conv)
    return {
        "ok": True,
        "case_number": cases.case_number(case["id"]),
        "case_number_spoken": cases.case_number_spoken(case["id"]),
        "say": "Flagged as life-threatening. A human dispatcher sees it now. Keep collecting the location and details.",
    }


@app.post("/tools/submit_rescue_request", dependencies=[Depends(require_tool_secret)])
async def tool_submit(request: Request):
    body = await _tool_body(request)
    phone, conv = _ids(body)
    case = await cases.upsert_rescue(body, phone=phone, conversation_id=conv)
    data = cases.serialize(case)
    need = []
    if not case.get("address") and not case.get("landmark"):
        need.append("the location")
    if not phone:
        need.append("a callback number")
    say = f"Request saved as case {data['case_number']}. Read the case number digit by digit."
    if need:
        say += f" Still missing: {', '.join(need)}. Ask for it, then call this tool again."
    return {
        "ok": True,
        "case_number": data["case_number"],
        "case_number_spoken": cases.case_number_spoken(case["id"]),
        "priority_label": data["label"],
        "say": say,
    }


@app.post("/tools/update_from_callback", dependencies=[Depends(require_tool_secret)])
async def tool_update_from_callback(request: Request):
    body = await _tool_body(request)
    return await cases.update_from_callback(body)


# ---------- ElevenLabs post-call webhook ----------

@app.post("/webhooks/elevenlabs")
async def elevenlabs_webhook(request: Request):
    raw = await request.body()
    if not elevenlabs.verify_webhook(raw, request.headers.get("elevenlabs-signature")):
        return JSONResponse({"error": "invalid signature"}, status_code=401)
    try:
        event = json.loads(raw)
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)
    log.info("webhook %s for conversation %s", event.get("type"), (event.get("data") or {}).get("conversation_id"))
    cases.spawn(cases.handle_post_call(event))
    return {"status": "received"}


# ---------- dispatcher API ----------

class AssignBody(BaseModel):
    unit: str = Field(min_length=1, max_length=80)
    eta_minutes: int | None = Field(default=None, ge=0, le=600)
    call_back: bool = True


class StatusBody(BaseModel):
    status: str


class IntakeTextBody(BaseModel):
    text: str = Field(min_length=10, max_length=4000)
    callback_number: str | None = None


class SurgeBody(BaseModel):
    count: int = Field(default=300, ge=1, le=2000)
    seconds: float = Field(default=60, ge=5, le=600)


@app.get("/api/health")
async def health():
    return {"ok": True, "timescale": db.HAS_TIMESCALE, "features": config.feature_flags(),
            "surge_running": simulator.running()}


@app.get("/api/cases", dependencies=[Depends(require_dispatch_key)])
async def list_cases(include_closed: bool = False):
    rows = await db.list_cases(include_closed=include_closed)
    return [cases.serialize(r) for r in rows]


@app.get("/api/cases/{case_id}", dependencies=[Depends(require_dispatch_key)])
async def get_case(case_id: int):
    case = await db.get_case(case_id)
    if not case:
        raise HTTPException(404, "case not found")
    data = cases.serialize(case)
    data["memory"] = await memory.recall(case.get("phone")) if not cases.is_fake_phone(case.get("phone")) else []
    return data


@app.get("/api/cases/{case_id}/recordings/{conversation_id}/audio",
         dependencies=[Depends(require_dispatch_key_or_query)])
async def recording_audio(case_id: int, conversation_id: str,
                          range_header: str | None = Header(default=None, alias="range")):
    """Proxy one call recording from ElevenLabs, so the API key stays on the server."""
    case = await db.get_case(case_id)
    if not case or conversation_id not in (case.get("conversation_ids") or []):
        raise HTTPException(404, "recording not found")
    audio = await elevenlabs.get_conversation_audio(conversation_id)
    if not audio:
        raise HTTPException(404, "no recording for this call (is audio saving on in ElevenLabs?)")
    body, content_type = audio
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    span = _byte_range(range_header, len(body))
    if span is None:
        return Response(body, media_type=content_type, headers=headers)
    start, end = span
    if start >= len(body) or end < start:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{len(body)}"})
    headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
    return Response(body[start:end + 1], status_code=206, media_type=content_type, headers=headers)


def _byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """'bytes=100-' / 'bytes=100-199' / 'bytes=-500' -> (start, end) inclusive. Browsers need this to seek."""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[6:].strip().partition("-")
    try:
        if not first:
            return max(0, size - int(last)), size - 1
        return int(first), min(int(last), size - 1) if last else size - 1
    except ValueError:
        return None


@app.get("/api/stats", dependencies=[Depends(require_dispatch_key)])
async def stats():
    return await db.stats()


@app.post("/api/cases/{case_id}/assign", dependencies=[Depends(require_dispatch_key)])
async def assign(case_id: int, body: AssignBody):
    try:
        case = await cases.assign(case_id, body.unit.strip(), body.eta_minutes, body.call_back)
    except LookupError:
        raise HTTPException(404, "case not found")
    return cases.serialize(case)


@app.post("/api/cases/{case_id}/callback", dependencies=[Depends(require_dispatch_key)])
async def retry_callback(case_id: int):
    case = await db.get_case(case_id)
    if not case or not case.get("unit"):
        raise HTTPException(400, "assign a unit first")
    case = await cases.assign(case_id, case["unit"], case.get("eta_minutes"), True)
    return cases.serialize(case)


@app.post("/api/cases/{case_id}/status", dependencies=[Depends(require_dispatch_key)])
async def set_status(case_id: int, body: StatusBody):
    try:
        case = await cases.set_status(case_id, body.status)
    except ValueError:
        raise HTTPException(400, "status must be open, assigned, rescued or closed")
    except LookupError:
        raise HTTPException(404, "case not found")
    return cases.serialize(case)


class LocationBody(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


@app.post("/api/cases/{case_id}/location", dependencies=[Depends(require_dispatch_key)])
async def set_location(case_id: int, body: LocationBody):
    try:
        case = await cases.set_location(case_id, body.lat, body.lng)
    except LookupError:
        raise HTTPException(404, "case not found")
    return cases.serialize(case)


@app.post("/api/intake/text", dependencies=[Depends(require_dispatch_key)])
async def intake_text(body: IntakeTextBody):
    """Paste a social media rescue post or text message; Gemini turns it into a case."""
    if not config.GEMINI_API_KEYS:
        raise HTTPException(400, "Set GEMINI_API_KEYS (or GEMINI_API_KEY) to use text intake")
    extraction = await gemini.extract_from_text(body.text)
    if not extraction:
        raise HTTPException(502, "Gemini could not read that post. Try again.")
    if not extraction.get("is_rescue_request"):
        raise HTTPException(422, "That doesn't look like a rescue request.")
    if not (extraction.get("address") or extraction.get("landmark")):
        raise HTTPException(422, "No location found in that post.")
    phone = cases.normalize_phone(body.callback_number) or cases.normalize_phone(extraction.get("callback_number"))
    case = await cases.upsert_rescue(extraction, phone=phone, source="social",
                                     enriched_summary=extraction.get("summary_en"))
    case = await db.update_case(case["id"], {"transcript": [{"role": "user", "message": body.text.strip(),
                                                             "call": "social"}]})
    await cases.ground(case["id"])  # the post text is the "caller" here
    case = await db.get_case(case["id"])
    await cases.publish(case)
    return cases.serialize(case)


@app.post("/api/demo/surge", dependencies=[Depends(require_dispatch_key)])
async def start_surge(body: SurgeBody | None = None):
    body = body or SurgeBody()
    if not simulator.start(body.count, body.seconds):
        raise HTTPException(409, "A surge is already running")
    return {"ok": True, "count": body.count, "seconds": body.seconds}


@app.post("/api/demo/reset", dependencies=[Depends(require_dispatch_key)])
async def reset(all: bool = False):
    if simulator.running():
        raise HTTPException(409, "Wait for the surge to finish")
    removed = await db.delete_cases(None if all else "simulated")
    await hub.broadcast({"type": "reset", "removed": removed, "all": all})
    return {"removed": len(removed)}


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    # Browsers can't set headers on a WebSocket, so the dashboard sends the key as ?key=
    if not _dispatch_key_ok(ws.query_params.get("key")):
        await ws.close(code=4401)  # refused before any case data is sent
        return
    await hub.connect(ws)
    try:
        rows = await db.list_cases()
        await ws.send_text(json.dumps({"type": "snapshot", "cases": [cases.serialize(r) for r in rows],
                                       "stats": await db.stats(), "features": config.feature_flags()},
                                      default=str))
        while True:
            await ws.receive_text()  # keepalive pings from the dashboard
    except (WebSocketDisconnect, RuntimeError):  # newer Starlette raises a RuntimeError subclass if the tab closed mid-send
        pass
    finally:
        await hub.disconnect(ws)


# ---------- dashboard (built React app) ----------

if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path in {"docs", "redoc", "openapi.json"}:  # API docs are off: a clear 404, not the dashboard
            raise HTTPException(404, "Not found")
        dist = config.FRONTEND_DIST.resolve()
        file = (dist / path).resolve()
        if path and file.is_file() and dist in file.parents:
            return FileResponse(file)
        return FileResponse(config.FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def root():
        return {"lifeline": "API running. Build the dashboard (frontend/) or run `npm run dev` there."}
