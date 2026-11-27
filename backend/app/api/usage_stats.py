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


@router.get("/export.csv")
async def export_usage(days: int = 90):
    """Per-reply usage as CSV: model, tokens (counted from the stream, so an
    estimate for local models), time to first token, total time."""
    import csv
    import io
    import time as _time

    from fastapi.responses import Response

    from app.db.storage import _conn

    since = _time.time() - max(1, min(days, 3650)) * 86400
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_utc", "model", "role", "tokens_estimated", "first_token_ms", "total_ms"])
    with _conn() as conn:
        for r in conn.execute("SELECT created_at, model, role, token_count, first_token_ms, duration_ms FROM usage_events"
                              " WHERE created_at >= ? ORDER BY created_at", (since,)):
            w.writerow([_time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(r[0])), r[1], r[2] or "", r[3], r[4] or "", r[5]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="zenith-usage.csv"'})
