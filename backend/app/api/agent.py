"""Agent tool-call approval + audit trail.

  GET  /api/agent/tool-calls?conversation_id=...  — audit log for a conversation
  POST /api/agent/tool-calls/{id}/approve         — let a pending call run
  POST /api/agent/tool-calls/{id}/deny            — block it
  POST /api/agent/tool-calls/{id}/revert          — undo an already-applied file edit
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.services import agent_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/tool-calls")
async def list_tool_calls(conversation_id: str):
    return agent_service.list_tool_calls(conversation_id)


@router.post("/tool-calls/{call_id}/approve")
async def approve(call_id: str):
    if not agent_service.approve_tool_call(call_id, True):
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
        raise HTTPException(400, str(exc))
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
