"""Named, switchable system-prompt presets ("coding buddy", "blunt
editor", "research assistant"). A conversation with a persona selected
uses that persona's prompt instead of the one global system prompt from
Settings -> Memory & persona; conversations without one keep using the
global prompt, so this is additive, not a breaking change."""
from __future__ import annotations

import time
import uuid

from app.db.storage import _conn


def list_personas() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM personas ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]


def get_persona(persona_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM personas WHERE id = ?", (persona_id,)).fetchone()
        return dict(row) if row else None


def create_persona(name: str, system_prompt: str, icon: str | None = None) -> dict:
    pid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO personas (id, name, icon, system_prompt, created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, name.strip(), icon, system_prompt.strip(), now),
        )
    return {"id": pid, "name": name.strip(), "icon": icon, "system_prompt": system_prompt.strip(), "created_at": now}


def update_persona(persona_id: str, name: str | None = None, system_prompt: str | None = None,
                    icon: str | None = None) -> None:
    with _conn() as conn:
        if name is not None:
            conn.execute("UPDATE personas SET name = ? WHERE id = ?", (name.strip(), persona_id))
        if system_prompt is not None:
            conn.execute("UPDATE personas SET system_prompt = ? WHERE id = ?", (system_prompt.strip(), persona_id))
        if icon is not None:
            conn.execute("UPDATE personas SET icon = ? WHERE id = ?", (icon, persona_id))


def delete_persona(persona_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        conn.execute("UPDATE conversations SET persona_id = NULL WHERE persona_id = ?", (persona_id,))


def set_conversation_persona(conversation_id: str, persona_id: str | None) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE conversations SET persona_id = ? WHERE id = ?", (persona_id, conversation_id)
        )


def get_conversation_persona_prompt(conversation_id: str) -> str | None:
    """Returns the active persona's system prompt for this conversation,
    or None if no persona is set (caller falls back to the global one)."""
    with _conn() as conn:
        row = conn.execute(
            """SELECT p.system_prompt FROM conversations c
               JOIN personas p ON p.id = c.persona_id
               WHERE c.id = ?""",
            (conversation_id,),
        ).fetchone()
        return row["system_prompt"] if row else None
