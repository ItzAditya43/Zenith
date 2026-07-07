"""Lightweight ordered migration runner.

Keeps `cortex.db` upgradeable across versions without dropping data. Each
migration is a tuple `(version, name, callable)` where the callable takes
a `sqlite3.Connection` and applies forward-only changes.

The first time this runs, the baseline migration records the original
schema so even pre-migration databases upgrade cleanly.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

from app.core.config import db_path as _db_path
from app.core.logging import get_logger

log = get_logger(__name__)


def _baseline(conn: sqlite3.Connection) -> None:
    """Captures the original conversations/messages schema. Idempotent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT,
            route_role TEXT,
            route_reason TEXT,
            attachments TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
        """
    )


def _attachments_table(conn: sqlite3.Connection) -> None:
    """Persist upload metadata so it survives backend restarts."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            mime_type TEXT,
            size INTEGER NOT NULL,
            kind TEXT NOT NULL,
            conversation_id TEXT,
            message_id TEXT,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attachments_conversation
            ON attachments(conversation_id);
        """
    )


def _fts5_index(conn: sqlite3.Connection) -> None:
    """SQLite FTS5 virtual table over message content for fast
    sidebar search. The Python `sqlite3` module doesn't always have FTS5
    compiled in (e.g. some slim distros), so we probe first; if it's
    missing we record the migration as applied but skip the index — the
    search route falls back to a LIKE scan in that case."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
            "content, content_rowid='rowid', tokenize='unicode61')"
        )
    except sqlite3.OperationalError as exc:
        log.warning("migration.fts5_unavailable", error=str(exc))
        # Tag the schema with a row that lets the app know FTS5 is off.
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('fts5_available', '0')"
            )
        except Exception:
            pass
        return
    # Record the success so the app can take the FTS path confidently.
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('fts5_available', '1')"
        )
    except Exception:
        pass
    # Triggers: separate execute calls so a single failure doesn't
    # abort the whole migration. The triggers are pure indexing glue.
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
        END;"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
            DELETE FROM messages_fts WHERE rowid = old.rowid;
        END;"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
            DELETE FROM messages_fts WHERE rowid = old.rowid;
            INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
        END;"""
    )


# Ordered list — never reorder, only append.
MIGRATIONS: list[tuple[int, str, callable]] = [
    (1, "baseline", _baseline),
    (2, "attachments_table", _attachments_table),
    (3, "fts5_index", _fts5_index),
]


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  version INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  applied_at REAL NOT NULL"
        ")"
    )
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"] or 0) if row else 0


def current_version(conn: sqlite3.Connection) -> int:
    """Public alias of `_current_version` so tests / external callers
    can ask the DB what schema_version it has without re-implementing."""
    return _current_version(conn)


@dataclass
class MigrationReport:
    """Outcome of one `run_migrations` call.

    `applied`  — versions that were just applied during this call.
    `skipped`  — versions that were already applied (and therefore skipped)."""
    applied: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)


def _run_migrations_on(conn: sqlite3.Connection) -> MigrationReport:
    report = MigrationReport()
    already = _current_version(conn)
    for version, name, fn in MIGRATIONS:
        if version <= already:
            report.skipped.append(version)
            continue
        log.info("migration.apply", version=version, name=name)
        fn(conn)
        conn.execute(
            "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, time.time()),
        )
        report.applied.append(version)
    conn.commit()
    return report


def run_migrations(conn: sqlite3.Connection | None = None) -> MigrationReport:
    """Apply any not-yet-applied migrations and return a report.

    When `conn` is None (the production startup path), a fresh connection
    to the default `DB_PATH` is opened and closed. Tests pass their own
    connection to share state with the rest of the suite."""
    if conn is None:
        own = sqlite3.connect(str(_db_path()))
        own.row_factory = sqlite3.Row
        try:
            return _run_migrations_on(own)
        finally:
            own.close()
    return _run_migrations_on(conn)
