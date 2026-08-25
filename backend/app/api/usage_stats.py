"""Extended usage stats: latency percentiles and per-model comparison.

Separate from the `/api/usage/summary` endpoint already exposed in
system.py (owned by another agent this round) — kept here rather than
extending that file to avoid touching it. This duplicates the "hit the
usage_events table" concern across two files; a future cleanup could fold
this into system.py's usage endpoint once ownership isn't split.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/stats")
async def usage_stats(days: int = 14):
    """Latency percentiles (p50/p90/p99) and a per-model comparison
    (turn count, avg latency, avg tokens/sec) over the trailing window."""
    from app.db import storage

    return {
        "latency_percentiles": storage.usage_latency_percentiles(days),
        "by_model": storage.usage_by_model(days),
    }
