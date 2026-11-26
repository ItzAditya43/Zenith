"""Agent tool-call approval + audit trail.

  GET  /api/agent/tool-calls?conversation_id=...  — audit log for a conversation
  POST /api/agent/tool-calls/{id}/approve         — let a pending call run
  POST /api/agent/tool-calls/{id}/deny            — block it
  POST /api/agent/tool-calls/{id}/revert          — undo an already-applied file edit
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings

from app.core.logging import get_logger
from app.services import agent_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/tool-calls")
async def list_tool_calls(conversation_id: str):
    return agent_service.list_tool_calls(conversation_id)


class ApproveBody(BaseModel):
    rejected_hunks: list[int] | None = None


@router.post("/tool-calls/{call_id}/approve")
async def approve(call_id: str, body: ApproveBody | None = None):
    if not agent_service.approve_tool_call(call_id, True, body.rejected_hunks if body else None):
        raise HTTPException(404, "No pending tool call with that id (already resolved or timed out).")
    return {"ok": True}


@router.post("/tool-calls/{call_id}/deny")
async def deny(call_id: str):
    if not agent_service.approve_tool_call(call_id, False):
        raise HTTPException(404, "No pending tool call with that id (already resolved or timed out).")
    return {"ok": True}


@router.post("/tool-calls/{call_id}/revert")
async def revert(call_id: str):
    try:
        message = agent_service.revert_tool_call(call_id)
    except agent_service.AgentError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "message": message}


@router.get("/runs")
async def list_runs(conversation_id: str):
    """Agent runs (one per user turn) that made at least one revertible
    file edit — powers the 'undo this whole run' affordance."""
    return agent_service.list_runs(conversation_id)


@router.post("/runs/{run_id}/revert")
async def revert_run(run_id: str):
    messages = agent_service.revert_run(run_id)
    return {"ok": True, "messages": messages}


# ---- background runs + run review ------------------------------------------

class BackgroundCreate(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=20000)
    model: str | None = Field(default=None, max_length=200)


@router.post("/background")
async def queue_background_run(body: BackgroundCreate):
    """Queue an agent task that keeps running with the window closed."""
    from app.services import background_runs

    if not bool(settings.get("agent_enabled", False)):
        raise HTTPException(400, "Turn on agent tools in Settings first.")
    try:
        return background_runs.enqueue(body.conversation_id, body.prompt, body.model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/background")
async def list_background_runs(conversation_id: str | None = None, since: float | None = None):
    from app.services import background_runs

    return background_runs.list_runs(conversation_id, since)


@router.get("/background/{bid}")
async def get_background_run(bid: str):
    from app.services import background_runs

    run = background_runs.get_run(bid)
    if not run:
        raise HTTPException(404, "No such task.")
    return run


@router.post("/background/{bid}/cancel")
async def cancel_background_run(bid: str):
    from app.services import background_runs

    if not background_runs.cancel(bid):
        raise HTTPException(409, "That task isn't running.")
    return {"ok": True}


@router.post("/background/{bid}/reviewed")
async def mark_background_reviewed(bid: str):
    from app.services import background_runs

    if not background_runs.mark_reviewed(bid):
        raise HTTPException(404, "No such task.")
    return {"ok": True}


@router.get("/runs/{run_id}/review")
async def review_run(run_id: str):
    """Changed files, diffs, commands, checks and tool activity for one run."""
    from app.services import background_runs

    return background_runs.review(run_id)

