import base64
import json
import os
import re
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from sqlalchemy import text
from sqlmodel import Session, col, or_, select

from app.auth import require_admin
from app.db import get_session
from app.models import Hook
from app.signatures import verify

app = FastAPI(title="Webhook Inbox", version="0.1.0")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_BODY = 4 * 1024 * 1024  # Vercel request limit is ~4.5 MB
CAPTURE_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
# Headers not forwarded on replay (hop-by-hop, platform-added, or recomputed).
SKIP_REPLAY = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}
SKIP_PREFIXES = ("x-vercel-", "x-forwarded-", "x-real-ip", "forwarded", "cf-")


# ---------- helpers ----------

def _encode_body(raw: bytes) -> tuple[str, bool]:
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        return base64.b64encode(raw).decode(), True


def _raw_body(hook: Hook) -> bytes:
    return base64.b64decode(hook.body) if hook.body_is_base64 else hook.body.encode()


def _pretty(hook: Hook) -> str:
    if hook.body_is_base64:
        return f"[binary, base64]\n{hook.body}"
    try:
        return json.dumps(json.loads(hook.body), indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        return hook.body


def _get(session: Session, hook_id: int) -> Hook:
    hook = session.get(Hook, hook_id)
    if not hook:
        raise HTTPException(404, "Hook not found")
    return hook


def _summary(h: Hook) -> dict:
    return {
        "id": h.id,
        "source": h.source,
        "method": h.method,
        "signature_status": h.signature_status,
        "content_type": h.content_type,
        "size": len(h.body),
        "received_at": h.received_at.isoformat(),
    }


def _query(session: Session, source: str | None, q: str | None, limit: int) -> list[Hook]:
    stmt = select(Hook).order_by(col(Hook.id).desc()).limit(min(limit, 200))
    if source:
        stmt = stmt.where(Hook.source == source)
    if q:
        stmt = stmt.where(or_(col(Hook.body).contains(q), col(Hook.url).contains(q)))
    return list(session.exec(stmt))


async def _replay(hook: Hook, target_url: str) -> dict:
    headers = {
        k: v for k, v in hook.headers.items()
        if k.lower() not in SKIP_REPLAY and not k.lower().startswith(SKIP_PREFIXES)
    }
    headers["x-replayed-from"] = f"webhook-inbox/{hook.id}"
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            r = await client.request(hook.method, target_url, headers=headers, content=_raw_body(hook))
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {
        "ok": r.is_success,
        "status": r.status_code,
        "elapsed_ms": round((time.perf_counter() - start) * 1000),
        "response": r.text[:2000],
    }


# ---------- capture (public) ----------

@app.api_route("/hook/{source}", methods=CAPTURE_METHODS)
async def capture(source: str, request: Request, session: Session = Depends(get_session)):
    if not SOURCE_RE.match(source):
        raise HTTPException(404, "Invalid source name")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Payload too large")

    headers = dict(request.headers)
    url = str(request.url)
    body, is_b64 = _encode_body(raw)
    hook = Hook(
        source=source,
        method=request.method,
        url=url,
        headers=headers,
        body=body,
        body_is_base64=is_b64,
        content_type=request.headers.get("content-type"),
        ip=request.headers.get("x-forwarded-for", request.client.host if request.client else None),
        signature_status=verify(source, request.method, url, headers, raw),
    )
    session.add(hook)
    session.commit()
    session.refresh(hook)
    return {"ok": True, "id": hook.id}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/cron/keepalive")
def keepalive(request: Request, session: Session = Depends(get_session)):
    """Hit by Vercel Cron so the Supabase free project never goes idle for a week."""
    secret = os.getenv("CRON_SECRET")
    if not secret or request.headers.get("authorization") != f"Bearer {secret}":
        raise HTTPException(401, "Unauthorized")
    session.exec(text("SELECT 1"))
    return {"ok": True}


# ---------- JSON API (admin) ----------

class ReplayIn(BaseModel):
    target_url: HttpUrl


@app.get("/api/hooks", dependencies=[Depends(require_admin)])
def list_hooks(
    source: str | None = None, q: str | None = None, limit: int = 50,
    session: Session = Depends(get_session),
):
    return [_summary(h) for h in _query(session, source, q, limit)]


@app.get("/api/hooks/{hook_id}", dependencies=[Depends(require_admin)])
def get_hook(hook_id: int, session: Session = Depends(get_session)):
    return _get(session, hook_id)


@app.post("/api/hooks/{hook_id}/replay", dependencies=[Depends(require_admin)])
async def replay_hook(hook_id: int, payload: ReplayIn, session: Session = Depends(get_session)):
    return await _replay(_get(session, hook_id), str(payload.target_url))


@app.delete("/api/hooks/{hook_id}", dependencies=[Depends(require_admin)])
def delete_hook(hook_id: int, session: Session = Depends(get_session)):
    session.delete(_get(session, hook_id))
    session.commit()
    return {"ok": True}


# ---------- dashboard (admin) ----------

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def dashboard(
    request: Request, source: str | None = None, q: str | None = None,
    session: Session = Depends(get_session),
):
    sources = sorted(session.exec(select(Hook.source).distinct()).all())
    return templates.TemplateResponse(
        request, "index.html",
        {"hooks": _query(session, source, q, 100), "sources": sources, "source": source, "q": q or ""},
    )


@app.get("/h/{hook_id}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def detail(request: Request, hook_id: int, session: Session = Depends(get_session)):
    hook = _get(session, hook_id)
    return templates.TemplateResponse(
        request, "detail.html", {"hook": hook, "pretty": _pretty(hook), "result": None, "target": ""}
    )


@app.post("/h/{hook_id}/replay", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def detail_replay(
    request: Request, hook_id: int, target_url: str = Form(...),
    session: Session = Depends(get_session),
):
    hook = _get(session, hook_id)
    if not target_url.startswith(("http://", "https://")):
        result = {"ok": False, "error": "Target must start with http:// or https://"}
    else:
        result = await _replay(hook, target_url)
    return templates.TemplateResponse(
        request, "detail.html",
        {"hook": hook, "pretty": _pretty(hook), "result": result, "target": target_url},
    )
