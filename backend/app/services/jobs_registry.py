"""In-memory registry of background-loop run status.

Tracks, for each named background job (the sweeper/scanner/runner loops in
`app.main`), when it last ran, whether it succeeded, how long it took, and
any detail message. This is process-lifetime state only — not persisted to
the DB. Restarting the app is a legitimate way to reset it; there's no
history beyond the most recent run per job.

Single-process asyncio, no real concurrent writers to the same job name, so
a plain dict is sufficient — no locking.
"""
from __future__ import annotations

import time
from typing import Literal

Status = Literal["success", "error"]

_jobs: dict[str, dict] = {}


def record_run(
    name: str,
    status: Status,
    duration_ms: float,
    detail: str | None = None,
) -> None:
    """Record the outcome of one run of the job `name`. Overwrites whatever
    was recorded for the previous run of the same job."""
    _jobs[name] = {
        "name": name,
        "last_run_at": time.time(),
        "last_status": status,
        "last_duration_ms": duration_ms,
        "last_detail": detail,
    }


def get_all() -> list[dict]:
    """Return the latest recorded status for every job that has ever called
    `record_run`, sorted by job name."""
    return [_jobs[name] for name in sorted(_jobs)]
