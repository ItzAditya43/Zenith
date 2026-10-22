"""Per-turn traces — see app/services/trace_service.py.

  GET /api/traces?conversation_id=&limit=   — newest first
  GET /api/traces/{id}
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.services import trace_service

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("")
async def list_traces(conversation_id: str | None = None, limit: int = Query(50, ge=1, le=500)):
    return await asyncio.to_thread(trace_service.list_traces, conversation_id, limit)


@router.get("/{trace_id}")
async def get_trace(trace_id: str):
    trace = await asyncio.to_thread(trace_service.get_trace, trace_id)
    if not trace:
        raise HTTPException(404, "No such trace.")
    return trace
