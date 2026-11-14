"""Workspace terminal: a shell in the conversation's working directory.

  GET    /api/terminal/available
  POST   /api/conversations/{id}/terminal        start (or reattach to) a shell
  GET    /api/terminal/{sid}/output?since=N      long-poll output after byte N
  POST   /api/terminal/{sid}/input               send keystrokes
  POST   /api/terminal/{sid}/resize              tell the shell the window size
  DELETE /api/terminal/{sid}                     close it

Two checks on top of the app-wide gates, because this is a shell:
- Only from this machine, unless `terminal_allow_remote` is on. A phone
  paired over the LAN can chat and approve agent steps, but doesn't get a
  raw shell by default.
- The browser Origin, when sent, must be one Zenith serves its UI from, so
  another website open in your browser can't drive the terminal.
See terminal_service.py for why this is HTTP rather than a WebSocket.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field

from app.api.files import _workdir
from app.core.config import settings
from app.core.security import is_local_client
from app.models.schemas import StrictModel
from app.services import terminal_service

router = APIRouter(prefix="/api", tags=["terminal"])


class StartRequest(StrictModel):
    cols: int = Field(default=100, ge=10, le=500)
    rows: int = Field(default=30, ge=2, le=200)


class InputRequest(StrictModel):
    data: str = Field(max_length=65536)


class ResizeRequest(StrictModel):
    cols: int = Field(ge=10, le=500)
    rows: int = Field(ge=2, le=200)


def _allowed_origin(origin: str) -> bool:
    from app.main import _LAN_ORIGIN_REGEX, _cors_origins

    if origin in _cors_origins():
        return True
    if settings.get("cors_allow_lan", False):
        import re

        return re.match(_LAN_ORIGIN_REGEX, origin) is not None
    return False


def _guard(request: Request) -> None:
    client = request.client.host if request.client else None
    if not is_local_client(client) and not settings.get("terminal_allow_remote", False):
        raise HTTPException(403, "The terminal only works on this machine. Turn on remote terminal access in Settings → Agent tools to allow other devices.")
    origin = request.headers.get("origin")
    if origin and not _allowed_origin(origin):
        raise HTTPException(403, "This page isn't allowed to use the terminal.")


def _session(request: Request, sid: str) -> terminal_service.Session:
    _guard(request)
    s = terminal_service.get(sid)
    if s is None:
        raise HTTPException(404, "Terminal session not found (it may have been closed after being idle).")
    return s


@router.get("/terminal/available")
async def available():
    return {"available": terminal_service.available()}


@router.post("/conversations/{conversation_id}/terminal")
async def start(conversation_id: str, request: Request, body: StartRequest | None = None):
    _guard(request)
    root = _workdir(conversation_id)
    body = body or StartRequest()
    try:
        s = terminal_service.start(conversation_id, str(root), body.cols, body.rows)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"session_id": s.id, "cwd": s.cwd, "alive": s.alive}


@router.get("/terminal/{sid}/output")
async def output(sid: str, request: Request, since: int = Query(0, ge=0), wait: float = Query(20.0, ge=0, le=30)):
    s = _session(request, sid)
    data, nxt, alive = await terminal_service.read(s, since, wait)
    return {
        "data": base64.b64encode(data).decode(),
        "next": nxt,
        "alive": alive,
        "exit_code": s.exit_code,
    }


@router.post("/terminal/{sid}/input")
async def send_input(sid: str, body: InputRequest, request: Request):
    s = _session(request, sid)
    try:
        terminal_service.write(s, body.data)
    except (RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@router.post("/terminal/{sid}/resize")
async def resize(sid: str, body: ResizeRequest, request: Request):
    s = _session(request, sid)
    terminal_service.resize(s, body.cols, body.rows)
    return {"ok": True}


@router.delete("/terminal/{sid}")
async def close(sid: str, request: Request):
    _guard(request)
    return {"closed": terminal_service.kill(sid)}
