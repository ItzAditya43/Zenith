"""Background job status endpoint: surfaces jobs_registry's in-memory
record of the last run of each background loop (orphan sweeper, folder
scanner, schedule runner, digest runner, email triage runner) so the
frontend can show whether they're actually running, without digging
through JSONL logs. See app/services/jobs_registry.py for the store.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.services import jobs_registry

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/status")
async def get_jobs_status() -> list[dict]:
    return jobs_registry.get_all()
