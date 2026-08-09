"""Ambient daily digest — see digest_service.py.

  GET  /api/digest/latest    — most recent digest, or null
  GET  /api/digest/history   — recent digests
  POST /api/digest/run-now   — generate one immediately (manual trigger)
"""
from __future__ import annotations

from fastapi import APIRouter

from app.db import storage
from app.services import digest_service

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("/latest")
async def get_latest():
    return storage.latest_digest()


@router.get("/history")
async def get_history():
    return storage.list_digests()


@router.post("/run-now")
async def run_now():
    digest = await digest_service.run_now()
    if digest is None:
        return {"generated": False, "reason": "Nothing new since the last digest."}
    return {"generated": True, "digest": digest}
