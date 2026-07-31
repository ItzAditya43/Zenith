"""Minimal SQLite persistence for conversations/messages — no ORM needed
for a schema this small, keeps startup instant and the file portable."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

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


# Public accessor for tests / external callers. Caller owns the
# connection (and must close it).
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL lets a reader (e.g. history fetch mid-stream) coexist with a
    # writer (message insert / orphan sweeper) without "database is locked".
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _conn():
    """One transaction per call: commits (or rolls back) and closes."""
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


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


def _row_to_message(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["attachments"] = json.loads(d["attachments"]) if d["attachments"] else []
    return d


def get_messages(conversation_id: str, active_only: bool = True) -> list[dict]:
    """Returns the conversation's messages in creation order. With
    `active_only` (the default, and what every existing call site wants:
    context-building, RAG indexing, title generation) this is the
    *current branch* — edited-away or regenerated-over messages are
    hidden. Pass `active_only=False` to see the full tree, e.g. for the
    branch switcher."""
    with _conn() as conn:
        sql = "SELECT * FROM messages WHERE conversation_id = ?"
        if active_only:
            sql += " AND active = 1"
        sql += " ORDER BY created_at ASC"
        rows = conn.execute(sql, (conversation_id,)).fetchall()
        return [_row_to_message(r) for r in rows]


def get_message(message_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return _row_to_message(row) if row else None


def get_last_active_message_id(conversation_id: str) -> str | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM messages WHERE conversation_id = ? AND active = 1 "
            "ORDER BY created_at DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return row["id"] if row else None


def get_siblings(conversation_id: str, parent_id: str | None) -> list[dict]:
    """All versions of "the message at this point" — every message
    sharing `parent_id`, active or not, oldest first. Length > 1 means
    there's a branch here."""
    with _conn() as conn:
        if parent_id is None:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? AND parent_id IS NULL "
                "ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? AND parent_id = ? "
                "ORDER BY created_at ASC",
                (conversation_id, parent_id),
            ).fetchall()
        return [_row_to_message(r) for r in rows]


def list_branch_points(conversation_id: str) -> dict[str, list[dict]]:
    """Every point in the tree with more than one version, keyed by
    parent_id ("root" for top-of-conversation branches). Powers the
    branch-switcher UI: it only needs to render at points that actually
    branch."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
    groups: dict[str, list[dict]] = {}
    for r in rows:
        d = _row_to_message(r)
        key = d["parent_id"] or "root"
        groups.setdefault(key, []).append(d)
    return {k: v for k, v in groups.items() if len(v) > 1}


def _deactivate_subtree(conn: sqlite3.Connection, root_parent_id: str) -> None:
    """Hides an old branch: deactivates every message reachable from
    `root_parent_id` (its children, their children, ...). Does not touch
    `root_parent_id` itself — the caller decides that message's fate."""
    frontier = [root_parent_id]
    while frontier:
        rows = conn.execute(
            "SELECT id FROM messages WHERE parent_id IN ({})".format(
                ",".join("?" * len(frontier))
            ),
            frontier,
        ).fetchall()
        ids = [r["id"] for r in rows]
        if not ids:
            return
        conn.execute(
            "UPDATE messages SET active = 0 WHERE id IN ({})".format(",".join("?" * len(ids))),
            ids,
        )
        frontier = ids


def deactivate_subtree(root_parent_id: str) -> None:
    """Public wrapper: hides every message below `root_parent_id` (used
    before creating a new branch there — edit-and-resend, regenerate)."""
    with _conn() as conn:
        _deactivate_subtree(conn, root_parent_id)


def deactivate_root(conversation_id: str) -> None:
    """Same idea as `deactivate_subtree`, for the special case of editing
    the very first message in a conversation — there's no real parent_id
    to pass (it's NULL), so root-level messages need their own path."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id FROM messages WHERE conversation_id = ? AND parent_id IS NULL",
            (conversation_id,),
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE messages SET active = 0 WHERE id = ?", (r["id"],))
            _deactivate_subtree(conn, r["id"])


def set_active_branch(conversation_id: str, message_id: str) -> None:
    """Switches the current branch to `message_id`: activates it,
    deactivates its siblings (and their whole subtrees), then restores
    the continuation *below* it by walking forward and re-activating the
    most-recently-created child at each level — i.e. resuming whatever
    was last being viewed down that path, not just the single message."""
    with _conn() as conn:
        row = conn.execute("SELECT parent_id FROM messages WHERE id = ?", (message_id,)).fetchone()
        if not row:
            return
        parent_id = row["parent_id"]
        siblings = get_siblings(conversation_id, parent_id)
        for sib in siblings:
            if sib["id"] == message_id:
                conn.execute("UPDATE messages SET active = 1 WHERE id = ?", (message_id,))
            else:
                conn.execute("UPDATE messages SET active = 0 WHERE id = ?", (sib["id"],))
                _deactivate_subtree(conn, sib["id"])

        current = message_id
        while True:
            children = conn.execute(
                "SELECT id FROM messages WHERE parent_id = ? ORDER BY created_at DESC",
                (current,),
            ).fetchall()
            if not children:
                break
            latest = children[0]["id"]
            conn.execute("UPDATE messages SET active = 1 WHERE id = ?", (latest,))
            for other in children[1:]:
                conn.execute("UPDATE messages SET active = 0 WHERE id = ?", (other["id"],))
                _deactivate_subtree(conn, other["id"])
            current = latest


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    model: str | None = None,
    route_role: str | None = None,
    route_reason: str | None = None,
    attachments: list | None = None,
    parent_id: str | None = None,
    created_at: float | None = None,
) -> dict:
    mid = str(uuid.uuid4())
    now = created_at if created_at is not None else time.time()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, model, route_role, route_reason,
                attachments, created_at, parent_id, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (mid, conversation_id, role, content, model, route_role, route_reason,
             json.dumps(attachments or []), now, parent_id),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
        )
    return {
        "id": mid, "conversation_id": conversation_id, "role": role, "content": content,
        "model": model, "route_role": route_role, "route_reason": route_reason,
        "attachments": attachments or [], "created_at": now, "parent_id": parent_id, "active": 1,
    }


def rename_conversation(conversation_id: str, title: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, time.time(), conversation_id),
        )


def set_conversation_workdir(conversation_id: str, workdir: str | None) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE conversations SET workdir = ? WHERE id = ?", (workdir, conversation_id)
        )


def get_conversation_workdir(conversation_id: str) -> str | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT workdir FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return row["workdir"] if row else None


def save_agent_checkpoint(conversation_id: str, state: str, model: str | None, iterations_used: int) -> None:
    import time
    with _conn() as conn:
        conn.execute(
            """INSERT INTO agent_checkpoints (conversation_id, state, model, iterations_used, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(conversation_id) DO UPDATE SET
                 state = excluded.state, model = excluded.model,
                 iterations_used = excluded.iterations_used, created_at = excluded.created_at""",
            (conversation_id, state, model, iterations_used, time.time()),
        )


def get_agent_checkpoint(conversation_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_checkpoints WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None


def clear_agent_checkpoint(conversation_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM agent_checkpoints WHERE conversation_id = ?", (conversation_id,))


def delete_conversation(conversation_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM agent_checkpoints WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


def delete_message(conversation_id: str, message_id: str) -> int:
    """Delete a message and everything downstream of it (its whole subtree in
    the parent/active branching model) — you can't keep a reply whose prompt
    is gone. Returns the number deleted. FTS is kept in sync by the
    messages_fts delete trigger."""
    with _conn() as conn:
        # BFS the subtree by parent_id.
        to_delete: list[str] = []
        frontier = [message_id]
        while frontier:
            mid = frontier.pop()
            to_delete.append(mid)
            rows = conn.execute(
                "SELECT id FROM messages WHERE conversation_id = ? AND parent_id = ?",
                (conversation_id, mid),
            ).fetchall()
            frontier.extend(r["id"] for r in rows)
        for mid in to_delete:
            conn.execute(
                "DELETE FROM messages WHERE id = ? AND conversation_id = ?",
                (mid, conversation_id),
            )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (time.time(), conversation_id),
        )
    return len(to_delete)


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


def search_documents(q: str) -> list[dict]:
    """Match uploaded documents by filename or by the text of their indexed
    chunks (source_kind='document', source_id=attachment id). Returns one
    row per document with a snippet from the first matching chunk."""
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.filename, a.kind, a.conversation_id,
                   (SELECT substr(ch.text, 1, 160) FROM chunks ch
                    WHERE ch.source_kind = 'document' AND ch.source_id = a.id
                      AND ch.text LIKE ? LIMIT 1) AS snip
            FROM attachments a
            WHERE a.filename LIKE ?
               OR EXISTS (SELECT 1 FROM chunks ch
                          WHERE ch.source_kind = 'document' AND ch.source_id = a.id
                            AND ch.text LIKE ?)
            ORDER BY a.created_at DESC
            LIMIT 20
            """,
            (like, like, like),
        ).fetchall()
        return [dict(r) for r in rows]


def search_memories(q: str) -> list[dict]:
    """Match stored memories by content."""
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT id, content, category, enabled
            FROM memories
            WHERE content LIKE ?
            ORDER BY updated_at DESC
            LIMIT 20
            """,
            (like,),
        ).fetchall()
        return [dict(r) for r in rows]


def search_all(q: str) -> dict:
    """Unified search: conversations (message content), documents (filename
    + chunk text), and memories (content) in one call, grouped by kind."""
    return {
        "conversations": search_conversations(q),
        "documents": search_documents(q),
        "memories": search_memories(q),
    }
