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


def create_conversation(title: str = "New chat", project_id: str | None = None) -> dict:
    cid = str(uuid.uuid4())
    now = time.time()
    workdir = None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at, project_id) VALUES (?, ?, ?, ?, ?)",
            (cid, title, now, now, project_id),
        )
        if project_id:
            proj = conn.execute("SELECT workdir FROM projects WHERE id = ?", (project_id,)).fetchone()
            if proj and proj["workdir"]:
                workdir = proj["workdir"]
                conn.execute("UPDATE conversations SET workdir = ? WHERE id = ?", (workdir, cid))
    return {
        "id": cid, "title": title, "created_at": now, "updated_at": now,
        "project_id": project_id, "workdir": workdir, "pinned": False,
        "tags": [], "share_token": None,
    }


def set_conversation_project(conversation_id: str, project_id: str | None) -> None:
    with _conn() as conn:
        conn.execute("UPDATE conversations SET project_id = ? WHERE id = ?", (project_id, conversation_id))
        if project_id:
            proj = conn.execute("SELECT workdir FROM projects WHERE id = ?", (project_id,)).fetchone()
            if proj and proj["workdir"]:
                conn.execute("UPDATE conversations SET workdir = ? WHERE id = ?", (proj["workdir"], conversation_id))


def create_project(name: str, workdir: str | None = None) -> dict:
    pid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, workdir, created_at) VALUES (?, ?, ?, ?)",
            (pid, name, workdir, now),
        )
    return {"id": pid, "name": name, "workdir": workdir, "created_at": now}


def list_projects() -> list[dict]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()]


def delete_project(project_id: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE conversations SET project_id = NULL WHERE project_id = ?", (project_id,))
        conn.execute("UPDATE memories SET project_id = NULL WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def _row_to_conversation(r: sqlite3.Row) -> dict:
    d = dict(r)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except (TypeError, ValueError):
        d["tags"] = []
    d["pinned"] = bool(d.get("pinned"))
    return d


def get_conversation(conversation_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return _row_to_conversation(row) if row else None


def list_conversations() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            # Pinned conversations float to the top, most-recent-first
            # within each group.
            "SELECT * FROM conversations ORDER BY pinned DESC, updated_at DESC"
        ).fetchall()
        return [_row_to_conversation(r) for r in rows]


def set_conversation_pinned(conversation_id: str, pinned: bool) -> None:
    with _conn() as conn:
        conn.execute("UPDATE conversations SET pinned = ? WHERE id = ?", (1 if pinned else 0, conversation_id))


def set_conversation_tags(conversation_id: str, tags: list[str]) -> None:
    with _conn() as conn:
        conn.execute("UPDATE conversations SET tags = ? WHERE id = ?", (json.dumps(tags), conversation_id))


def create_share_link(conversation_id: str) -> str:
    """Issues a fresh share token, replacing any previous one — resharing
    a conversation invalidates its old link rather than accumulating
    live tokens nobody remembers granting."""
    token = uuid.uuid4().hex
    with _conn() as conn:
        conn.execute("UPDATE conversations SET share_token = ? WHERE id = ?", (token, conversation_id))
    return token


def revoke_share_link(conversation_id: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE conversations SET share_token = NULL WHERE id = ?", (conversation_id,))


def get_conversation_by_share_token(token: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE share_token = ?", (token,)).fetchone()
        return _row_to_conversation(row) if row else None


def get_project_agent_mode(project_id: str | None) -> str | None:
    if not project_id:
        return None
    with _conn() as conn:
        row = conn.execute("SELECT agent_mode FROM projects WHERE id = ?", (project_id,)).fetchone()
        return row["agent_mode"] if row else None


def set_project_agent_mode(project_id: str, agent_mode: str | None) -> None:
    with _conn() as conn:
        conn.execute("UPDATE projects SET agent_mode = ? WHERE id = ?", (agent_mode, project_id))


def list_snippets() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM snippets ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def create_snippet(title: str, content: str) -> dict:
    sid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO snippets (id, title, content, created_at) VALUES (?, ?, ?, ?)",
            (sid, title, content, now),
        )
    return {"id": sid, "title": title, "content": content, "created_at": now}


def delete_snippet(snippet_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM snippets WHERE id = ?", (snippet_id,))


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
    speaker_persona_id: str | None = None,
) -> dict:
    mid = str(uuid.uuid4())
    now = created_at if created_at is not None else time.time()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, model, route_role, route_reason,
                attachments, created_at, parent_id, active, speaker_persona_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (mid, conversation_id, role, content, model, route_role, route_reason,
             json.dumps(attachments or []), now, parent_id, speaker_persona_id),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
        )
    return {
        "id": mid, "conversation_id": conversation_id, "role": role, "content": content,
        "model": model, "route_role": route_role, "route_reason": route_reason,
        "attachments": attachments or [], "created_at": now, "parent_id": parent_id, "active": 1,
        "speaker_persona_id": speaker_persona_id,
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


def record_skill_run(
    conversation_id: str, signature: str, tool_sequence: list[str], prompt_template: str
) -> dict | None:
    """Called once per completed agent turn with that turn's ordered tool-name
    signature. The first time a signature is seen it's just noted; the second
    time the exact same sequence recurs, it's auto-promoted into a saved
    skill — that repetition is the signal a real reusable playbook exists.
    Returns the newly-created skill dict, or None if nothing new was saved."""
    with _conn() as conn:
        existing = conn.execute("SELECT * FROM skills WHERE signature = ?", (signature,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE skills SET use_count = use_count + 1 WHERE signature = ?", (signature,)
            )
            return None
        # Heuristic promotion: a distinctive (2+ step) sequence recurring at
        # all is worth surfacing; single-tool sequences are too generic.
        if len(tool_sequence) < 2:
            return None
        seen_before = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?", (f"skillseen:{signature}",)
        ).fetchone()
        if not seen_before:
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                (f"skillseen:{signature}", conversation_id),
            )
            return None
        skill_id = str(uuid.uuid4())
        name = " → ".join(tool_sequence[:4]) + ("…" if len(tool_sequence) > 4 else "")
        now = time.time()
        conn.execute(
            """INSERT INTO skills
               (id, name, description, signature, prompt_template, tool_sequence,
                source_conversation_id, auto_detected, use_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 2, ?)""",
            (skill_id, name, f"Auto-detected: repeats the {len(tool_sequence)}-step "
             f"{'/'.join(tool_sequence)} sequence.", signature, prompt_template,
             json.dumps(tool_sequence), conversation_id, now),
        )
        return {
            "id": skill_id, "name": name, "signature": signature,
            "prompt_template": prompt_template, "tool_sequence": tool_sequence,
            "source_conversation_id": conversation_id, "auto_detected": 1,
            "use_count": 2, "created_at": now,
        }


def record_skill_correction(
    conversation_id: str, failure: str, recovery_sequence: list[str], prompt_template: str
) -> dict | None:
    """Error-driven self-scripting: a tool call failed mid-turn, but the
    agent kept going and still reached a real answer via some other
    sequence. That recovery path — what actually worked after the
    failure — is saved immediately (no repeat-detection wait, since the
    within-turn recovery is itself the valuable signal), so a similar
    future task can skip straight past the dead end."""
    if not failure or len(recovery_sequence) < 1:
        return None
    signature = f"correction:{failure[:60]}|{'|'.join(recovery_sequence)}"
    with _conn() as conn:
        existing = conn.execute("SELECT id FROM skills WHERE signature = ?", (signature,)).fetchone()
        if existing:
            conn.execute("UPDATE skills SET use_count = use_count + 1 WHERE signature = ?", (signature,))
            return None
        skill_id = str(uuid.uuid4())
        name = f"Recovery: {failure.split(':')[0]} failed → {' → '.join(recovery_sequence[:3])}"
        now = time.time()
        conn.execute(
            """INSERT INTO skills
               (id, name, description, signature, prompt_template, tool_sequence,
                source_conversation_id, auto_detected, use_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)""",
            (skill_id, name, f"Auto-detected correction: after '{failure}' failed, "
             f"this sequence worked instead: {'/'.join(recovery_sequence)}.",
             signature, prompt_template, json.dumps(recovery_sequence), conversation_id, now),
        )
        return {
            "id": skill_id, "name": name, "signature": signature,
            "prompt_template": prompt_template, "tool_sequence": recovery_sequence,
            "source_conversation_id": conversation_id, "auto_detected": 1,
            "use_count": 1, "created_at": now,
        }


def list_skills() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM skills ORDER BY use_count DESC, created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tool_sequence"] = json.loads(d["tool_sequence"])
        out.append(d)
    return out


def delete_skill(skill_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))


def save_skill_manual(name: str, prompt_template: str, description: str = "") -> dict:
    with _conn() as conn:
        skill_id = str(uuid.uuid4())
        signature = f"manual:{skill_id}"
        now = time.time()
        conn.execute(
            """INSERT INTO skills
               (id, name, description, signature, prompt_template, tool_sequence,
                source_conversation_id, auto_detected, use_count, created_at)
               VALUES (?, ?, ?, ?, ?, '[]', NULL, 0, 0, ?)""",
            (skill_id, name, description, signature, prompt_template, now),
        )
    return {
        "id": skill_id, "name": name, "description": description, "signature": signature,
        "prompt_template": prompt_template, "tool_sequence": [], "auto_detected": 0,
        "use_count": 0, "created_at": now,
    }


def create_calendar_event(
    title: str, start_ts: float, end_ts: float | None = None, description: str = "",
    all_day: bool = False, source_conversation_id: str | None = None,
) -> dict:
    eid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO calendar_events
               (id, title, description, start_ts, end_ts, all_day, source_conversation_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, title, description, start_ts, end_ts, 1 if all_day else 0, source_conversation_id, now),
        )
    return {
        "id": eid, "title": title, "description": description, "start_ts": start_ts,
        "end_ts": end_ts, "all_day": 1 if all_day else 0,
        "source_conversation_id": source_conversation_id, "created_at": now,
    }


def list_calendar_events(from_ts: float | None = None, to_ts: float | None = None) -> list[dict]:
    with _conn() as conn:
        sql = "SELECT * FROM calendar_events WHERE 1=1"
        params: list = []
        if from_ts is not None:
            sql += " AND (end_ts IS NULL AND start_ts >= ? OR end_ts >= ?)"
            params += [from_ts, from_ts]
        if to_ts is not None:
            sql += " AND start_ts <= ?"
            params.append(to_ts)
        sql += " ORDER BY start_ts ASC"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def delete_calendar_event(event_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))


def create_note(content: str, color: str = "default") -> dict:
    nid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO notes (id, content, color, pinned, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            (nid, content, color, now, now),
        )
    return {"id": nid, "content": content, "color": color, "pinned": 0, "created_at": now, "updated_at": now}


def list_notes() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notes ORDER BY pinned DESC, updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def update_note(note_id: str, content: str | None = None, color: str | None = None, pinned: bool | None = None) -> None:
    fields, params = [], []
    if content is not None:
        fields.append("content = ?")
        params.append(content)
    if color is not None:
        fields.append("color = ?")
        params.append(color)
    if pinned is not None:
        fields.append("pinned = ?")
        params.append(1 if pinned else 0)
    if not fields:
        return
    fields.append("updated_at = ?")
    params.append(time.time())
    params.append(note_id)
    with _conn() as conn:
        conn.execute(f"UPDATE notes SET {', '.join(fields)} WHERE id = ?", params)


def delete_note(note_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))


def create_todo(text: str, due_ts: float | None = None) -> dict:
    tid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO todos (id, text, done, due_ts, created_at, updated_at) VALUES (?, ?, 0, ?, ?, ?)",
            (tid, text, due_ts, now, now),
        )
    return {"id": tid, "text": text, "done": 0, "due_ts": due_ts, "created_at": now, "updated_at": now}


def list_todos() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM todos ORDER BY done ASC, (due_ts IS NULL), due_ts ASC, created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def update_todo(todo_id: str, text: str | None = None, done: bool | None = None, due_ts: float | None = "__unset__") -> None:
    fields, params = [], []
    if text is not None:
        fields.append("text = ?")
        params.append(text)
    if done is not None:
        fields.append("done = ?")
        params.append(1 if done else 0)
    if due_ts != "__unset__":
        fields.append("due_ts = ?")
        params.append(due_ts)
    if not fields:
        return
    fields.append("updated_at = ?")
    params.append(time.time())
    params.append(todo_id)
    with _conn() as conn:
        conn.execute(f"UPDATE todos SET {', '.join(fields)} WHERE id = ?", params)


def delete_todo(todo_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))


def is_email_flagged_seen(message_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM email_flags WHERE message_id = ?", (message_id,)).fetchone()
        return row is not None


def record_email_flag(message_id: str, subject: str, sender: str, reason: str, urgent: bool) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO email_flags
               (message_id, subject, sender, reason, urgent, seen, flagged_at)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (message_id, subject, sender, reason, 1 if urgent else 0, time.time()),
        )


def list_urgent_email_flags(unseen_only: bool = True) -> list[dict]:
    with _conn() as conn:
        sql = "SELECT * FROM email_flags WHERE urgent = 1"
        if unseen_only:
            sql += " AND seen = 0"
        sql += " ORDER BY flagged_at DESC"
        return [dict(r) for r in conn.execute(sql).fetchall()]


def mark_email_flags_seen() -> None:
    with _conn() as conn:
        conn.execute("UPDATE email_flags SET seen = 1 WHERE seen = 0")


def create_research_report(conversation_id: str | None, query: str, answer: str, sources: list[dict]) -> dict:
    rid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO research_reports (id, conversation_id, query, answer, sources, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (rid, conversation_id, query, answer, json.dumps(sources), now),
        )
    return {"id": rid, "conversation_id": conversation_id, "query": query, "answer": answer, "sources": sources, "created_at": now}


def list_research_reports() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM research_reports ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"])
        out.append(d)
    return out


def get_research_report(report_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM research_reports WHERE id = ?", (report_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["sources"] = json.loads(d["sources"])
    return d


def delete_research_report(report_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM research_reports WHERE id = ?", (report_id,))


def set_group_personas(conversation_id: str, persona_ids: list[str] | None) -> None:
    value = json.dumps(persona_ids) if persona_ids else None
    with _conn() as conn:
        conn.execute("UPDATE conversations SET group_persona_ids = ? WHERE id = ?", (value, conversation_id))


def get_group_personas(conversation_id: str) -> list[str]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT group_persona_ids FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    if not row or not row["group_persona_ids"]:
        return []
    try:
        return json.loads(row["group_persona_ids"])
    except (json.JSONDecodeError, TypeError):
        return []


def record_usage_event(
    model: str, role: str | None, token_count: int, duration_ms: int, first_token_ms: int | None
) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO usage_events (id, model, role, token_count, duration_ms, first_token_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), model, role, token_count, duration_ms, first_token_ms, time.time()),
        )


def usage_summary(days: int = 14) -> dict:
    """Aggregates usage_events into: overall totals, a per-model
    breakdown, and a daily time series — token throughput and latency
    trends, not just a live snapshot."""
    since = time.time() - days * 86400
    with _conn() as conn:
        totals = conn.execute(
            """SELECT COUNT(*) AS turns, COALESCE(SUM(token_count), 0) AS tokens,
                      COALESCE(AVG(duration_ms), 0) AS avg_duration_ms,
                      COALESCE(AVG(first_token_ms), 0) AS avg_first_token_ms
               FROM usage_events WHERE created_at >= ?""",
            (since,),
        ).fetchone()
        by_model = conn.execute(
            """SELECT model, COUNT(*) AS turns, COALESCE(SUM(token_count), 0) AS tokens,
                      COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
               FROM usage_events WHERE created_at >= ?
               GROUP BY model ORDER BY turns DESC""",
            (since,),
        ).fetchall()
        daily = conn.execute(
            """SELECT date(created_at, 'unixepoch') AS day, COUNT(*) AS turns,
                      COALESCE(SUM(token_count), 0) AS tokens,
                      COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
               FROM usage_events WHERE created_at >= ?
               GROUP BY day ORDER BY day ASC""",
            (since,),
        ).fetchall()
    return {
        "totals": dict(totals),
        "by_model": [dict(r) for r in by_model],
        "daily": [dict(r) for r in daily],
    }


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


def search_notes(q: str) -> list[dict]:
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, content, color, pinned FROM notes WHERE content LIKE ? ORDER BY updated_at DESC LIMIT 20",
            (like,),
        ).fetchall()
        return [dict(r) for r in rows]


def search_todos(q: str) -> list[dict]:
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, text, done, due_ts FROM todos WHERE text LIKE ? ORDER BY created_at DESC LIMIT 20",
            (like,),
        ).fetchall()
        return [dict(r) for r in rows]


def search_calendar_events(q: str) -> list[dict]:
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, title, description, start_ts FROM calendar_events
               WHERE title LIKE ? OR description LIKE ? ORDER BY start_ts DESC LIMIT 20""",
            (like, like),
        ).fetchall()
        return [dict(r) for r in rows]


def search_research_reports(q: str) -> list[dict]:
    if not q or not q.strip():
        return []
    like = f"%{q.strip()}%"
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id, query, answer, created_at FROM research_reports
               WHERE query LIKE ? OR answer LIKE ? ORDER BY created_at DESC LIMIT 20""",
            (like, like),
        ).fetchall()
        return [dict(r) for r in rows]


def search_all(q: str) -> dict:
    """Unified search: conversations (message content), documents (filename
    + chunk text), memories, notes, to-dos, calendar events, and research
    reports — everything the sidebar search bar can jump you to, in one call."""
    return {
        "conversations": search_conversations(q),
        "documents": search_documents(q),
        "memories": search_memories(q),
        "notes": search_notes(q),
        "todos": search_todos(q),
        "calendar_events": search_calendar_events(q),
        "research_reports": search_research_reports(q),
    }
