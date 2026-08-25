"""Append-only history of `config.settings.set()` calls — see
migrations.py's `settings_history` table. Every real config change gets
logged here so the Settings history panel can show what changed and,
if needed, revert it. Logging is best-effort: a failure here must never
break the actual config write it's recording, same "never let ancillary
logging break the real operation" pattern as webhook_service.py /
memory_service.py.
"""
from __future__ import annotations

import json
import time
import uuid

from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)


def _row_to_dict(r) -> dict:
    d = dict(r)
    try:
        d["old_value"] = json.loads(d["old_value"]) if d["old_value"] is not None else None
    except Exception:
        pass
    try:
        d["new_value"] = json.loads(d["new_value"]) if d["new_value"] is not None else None
    except Exception:
        pass
    return d


def log_change(key: str, old_value, new_value) -> None:
    """Insert one history row. Best-effort — never raises."""
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO settings_history (id, key, old_value, new_value, changed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    key,
                    json.dumps(old_value),
                    json.dumps(new_value),
                    time.time(),
                ),
            )
    except Exception as exc:
        log.warning("settings_history.log_failed", key=key, error=str(exc))


def list_history(key: str | None = None, limit: int = 100) -> list[dict]:
    with _conn() as conn:
        if key:
            rows = conn.execute(
                "SELECT * FROM settings_history WHERE key = ? ORDER BY changed_at DESC LIMIT ?",
                (key, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM settings_history ORDER BY changed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def revert_to(history_id: str) -> dict:
    """Reverts a setting back to the `old_value` of the given history
    row. This itself logs a new history entry for the revert-as-a-change
    (via `config.settings.set`, which logs automatically) — the history
    is a genuine append-only log, never edited or erased in place."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM settings_history WHERE id = ?", (history_id,)
        ).fetchone()
    if row is None:
        raise ValueError(f"No settings_history row with id {history_id!r}")
    entry = _row_to_dict(row)
    key = entry["key"]
    old_value = entry["old_value"]

    from app.core.config import settings as config_settings

    config_settings.set(key, old_value)
    return {"key": key, "reverted_to": old_value}
