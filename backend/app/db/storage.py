"""Minimal SQLite persistence for conversations/messages — no ORM needed
for a schema this small, keeps startup instant and the file portable."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from app.core.config import db_path as _db_path
from app.db.migrations import run_migrations

SCHEMA = """
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


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


# Public alias so tests / external callers can use the same accessor
# as the internal module.
def _connect() -> sqlite3.Connection:
    return _conn()


def init_db() -> None:
    # Run ordered migrations (idempotent; tracks schema_version internally).
    # The baseline migration records the current schema as-is.
    run_migrations()


def create_conversation(title: str = "New chat") -> dict:
    cid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (cid, title, now, now),
        )
    return {"id": cid, "title": title, "created_at": now, "updated_at": now}


def list_conversations() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_messages(conversation_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["attachments"] = json.loads(d["attachments"]) if d["attachments"] else []
            out.append(d)
        return out


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    model: str | None = None,
    route_role: str | None = None,
    route_reason: str | None = None,
    attachments: list | None = None,
) -> dict:
    mid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, model, route_role, route_reason, attachments, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, conversation_id, role, content, model, route_role, route_reason,
             json.dumps(attachments or []), now),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
        )
    return {
        "id": mid, "conversation_id": conversation_id, "role": role, "content": content,
        "model": model, "route_role": route_role, "route_reason": route_reason,
        "attachments": attachments or [], "created_at": now,
    }


def rename_conversation(conversation_id: str, title: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, time.time(), conversation_id),
        )


def delete_conversation(conversation_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


def search_conversations(q: str) -> list[dict]:
    """Full-text search over message content. Returns distinct
    conversations with the matching snippet and message count. Uses
    SQLite FTS5 when available, falling back to a LIKE scan otherwise
    (or when FTS5 returns no hits for a prefix/stemming mismatch)."""
    if not q or not q.strip():
        return []
    term = q.strip()
    with _conn() as conn:
        # FTS5 path (prefix match so "tomato" finds "tomatoes").
        try:
            fts_query = term.replace('"', '""')
            rows = conn.execute(
                """
                SELECT m.conversation_id, c.title, snippet(messages_fts, 0, '<mark>', '</mark>', '…', 12) AS snip,
                       COUNT(*) AS hits, MAX(m.created_at) AS last_at
                FROM messages_fts
                JOIN messages m ON m.rowid = messages_fts.rowid
                JOIN conversations c ON c.id = m.conversation_id
                WHERE messages_fts MATCH ?
                GROUP BY m.conversation_id
                ORDER BY last_at DESC
                LIMIT 50
                """,
                (fts_query,),
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]
        except Exception:
            pass
        # Fallback: LIKE scan (also covers no-FTS5 builds and zero FTS hits).
        like = f"%{term}%"
        rows = conn.execute(
            """
            SELECT m.conversation_id, c.title, substr(m.content, 1, 200) AS snip,
                   COUNT(*) AS hits, MAX(m.created_at) AS last_at
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.content LIKE ?
            GROUP BY m.conversation_id
            ORDER BY last_at DESC
            LIMIT 50
            """,
            (like,),
        ).fetchall()
        return [dict(r) for r in rows]
