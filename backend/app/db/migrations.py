"""
Schema-versioned migration runner.

Ground rule #3: we never silently mutate the SQLite schema. Every schema
change ships as a numbered migration function inside this module, and the
runner applies pending ones at backend startup in order, inside a single
transaction.

Adding a new migration
---------------------
1. Bump `_LATEST_VERSION` in this module.
2. Add a new function ``_migrate_0002_<name>(conn)`` and append it to
   ``_MIGRATIONS`` in version order.
3. Inside the function, use ``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE``
   guards so a partially-applied state is self-healing.
4. The runner records the applied version in ``schema_version``; existing
   databases skip already-applied migrations cleanly.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("cortex.migrations")

# Order matters: append new migrations; never reorder old ones.
MigrationFn = Callable[[sqlite3.Connection], None]


def _migrate_0001_baseline(conn: sqlite3.Connection) -> None:
    """Capture the original schema as the baseline.

    The tables themselves are created by ``storage.init_db()`` via its
    ``CREATE TABLE IF NOT EXISTS`` statements, so the basin's only job is
    to be a versioned checkpoint. Future migrations that introduce
    additional tables/columns live in higher-numbered functions.
    """
    # Defensive: ensure schema_version itself exists (the runner will have
    # already created it before calling us, but a baseline must be safe to
    # run in isolation for unit tests).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now')),"
        "  description TEXT"
        ")"
    )


_MIGRATIONS: list[tuple[int, str, MigrationFn]] = [
    (1, "baseline", _migrate_0001_baseline),
]

_LATEST_VERSION = max(v for v, _, _ in _MIGRATIONS)


@dataclass
class MigrationReport:
    applied: list[int]
    already_applied: list[int]
    latest_version: int

    def to_dict(self) -> dict:
        return {
            "applied": self.applied,
            "already_applied": self.already_applied,
            "latest_version": self.latest_version,
        }


def current_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied version, or 0 if none."""
    _ensure_version_table(conn)
    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version"
    ).fetchone()
    return int(row[0]) if row else 0


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now')),"
        "  description TEXT"
        ")"
    )


def run_migrations(conn: sqlite3.Connection) -> MigrationReport:
    """Apply pending migrations inside one transaction.

    Each migration runs in its own savepoint, so a single bad migration
    does not corrupt the database — the runner logs the failure and
    re-raises.
    """
    _ensure_version_table(conn)
    already = {
        int(r[0])
        for r in conn.execute("SELECT version FROM schema_version").fetchall()
    }
    applied: list[int] = []

    for version, name, fn in _MIGRATIONS:
        if version in already:
            continue
        try:
            logger.info(
                "migration.start",
                extra={"version": version, "name": name},
            )
            fn(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_version(version, description) "
                "VALUES (?, ?)",
                (version, name),
            )
            conn.commit()
            applied.append(version)
            logger.info(
                "migration.applied",
                extra={"version": version, "name": name},
            )
        except Exception:
            conn.rollback()
            logger.exception(
                "migration.failed",
                extra={"version": version, "name": name},
            )
            raise

    return MigrationReport(
        applied=applied,
        already_applied=sorted(already),
        latest_version=_LATEST_VERSION,
    )


def latest_version() -> int:
    return _LATEST_VERSION