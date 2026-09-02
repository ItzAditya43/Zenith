"""Zenith as an MCP SERVER — the mirror image of `app/services/mcp_service.py`
(which lets Zenith's agent mode CONSUME other MCP servers). This module
exposes a slice of Zenith's own local data — memories, RAG-indexed
documents, notes, todos — as MCP tools that any other MCP-compatible
client (Claude Desktop, Cursor, etc.) can call.

Runs as a fully separate process from the FastAPI backend (`main.py`)
over stdio — it does not import or start the web app, and does not
require it to be running. It reads the SAME SQLite database by importing
the same `app.core.config`/`app.db.storage`/`app.services.*` modules
those already use, which resolve the DB path from the `CORTEX_DATA_DIR`
env var (see `app/core/config.py::_resolve_data_dir`). Point a client's
`env` at the right `CORTEX_DATA_DIR` and it sees the real Zenith data.

Deliberately read-only: no create/update/delete tools are exposed here,
so a misbehaving or overly eager external agent can't mutate a user's
notes/todos/memories through this surface.

Uses FastMCP (`mcp.server.fastmcp`), available in the installed `mcp`
package version — it turns a plain typed async function + docstring into
a fully-described MCP tool with almost no boilerplate, vs. hand-rolling
`list_tools`/`call_tool` dispatch with the low-level `Server` API.
"""
from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("zenith")


@mcp.tool()
async def zenith_memory_search(query: str) -> str:
    """Search the user's Zenith long-term memories (facts Zenith has
    learned about the user/projects over time) for a substring match.
    Use this to recall persistent facts about the user before answering
    questions about their preferences, projects, or past context.
    `query` is matched case-insensitively against memory content; pass an
    empty string to list all enabled memories."""
    from app.services.memory_service import list_memories

    def _run() -> str:
        memories = list_memories(include_disabled=False)
        q = query.strip().lower()
        if q:
            memories = [m for m in memories if q in (m.get("content") or "").lower()]
        if not memories:
            return f"No memories found matching '{query}'." if q else "No memories stored."
        lines = [f"Found {len(memories)} memor{'y' if len(memories) == 1 else 'ies'}:"]
        for i, m in enumerate(memories, 1):
            category = m.get("category") or "fact"
            lines.append(f"{i}. [{category}] {m.get('content', '')}")
        return "\n".join(lines)

    return await asyncio.to_thread(_run)


@mcp.tool()
async def zenith_rag_search(query: str, top_k: int = 5) -> str:
    """Search Zenith's RAG index — chunks of uploaded documents, indexed
    conversation messages, and indexed memories — for content relevant to
    `query`, using the same hybrid vector+lexical retrieval Zenith's own
    chat uses. Use this to ground answers in the user's own documents and
    past conversations. `top_k` caps how many chunks come back (default 5)."""
    from app.services import rag_service

    results = await asyncio.to_thread(rag_service.retrieve, query, None, top_k)
    if not results:
        return f"No RAG results found for '{query}'."
    lines = [f"Found {len(results)} relevant chunk(s):"]
    for i, r in enumerate(results, 1):
        source = r.get("source_kind") or "document"
        text = (r.get("text") or "").strip()
        if len(text) > 500:
            text = text[:500] + "..."
        lines.append(f"{i}. [{source}] {text}")
    return "\n".join(lines)


@mcp.tool()
async def zenith_notes_list() -> str:
    """List all of the user's Zenith notes (pinned notes first, then most
    recently updated). Use this to see what the user has jotted down —
    quick freeform notes are distinct from todos (which carry a
    done/status state) and from memories (auto-extracted facts)."""
    from app.db.storage import list_notes

    def _run() -> str:
        notes = list_notes()
        if not notes:
            return "No notes found."
        lines = [f"Found {len(notes)} note(s):"]
        for i, n in enumerate(notes, 1):
            pin = " [pinned]" if n.get("pinned") else ""
            lines.append(f"{i}. {n.get('content', '')}{pin}")
        return "\n".join(lines)

    return await asyncio.to_thread(_run)


@mcp.tool()
async def zenith_notes_search(query: str) -> str:
    """Search the user's Zenith notes for a substring match on their
    content. Use this instead of `zenith_notes_list` when you're looking
    for a specific note rather than browsing all of them."""
    from app.db.storage import search_notes

    def _run() -> str:
        notes = search_notes(query)
        if not notes:
            return f"No notes found matching '{query}'."
        lines = [f"Found {len(notes)} note(s) matching '{query}':"]
        for i, n in enumerate(notes, 1):
            pin = " [pinned]" if n.get("pinned") else ""
            lines.append(f"{i}. {n.get('content', '')}{pin}")
        return "\n".join(lines)

    return await asyncio.to_thread(_run)


@mcp.tool()
async def zenith_todos_list(status: str | None = None) -> str:
    """List the user's Zenith todos, optionally filtered by `status`
    ("todo", "in_progress", or "done"). Omit `status` to list all todos
    regardless of state. Use this to check what the user has outstanding
    or already finished before suggesting next steps."""
    from app.db.storage import list_todos

    def _run() -> str:
        todos = list_todos()
        if status:
            todos = [t for t in todos if t.get("status") == status]
        if not todos:
            return f"No todos found with status '{status}'." if status else "No todos found."
        lines = [f"Found {len(todos)} todo(s):"]
        for i, t in enumerate(todos, 1):
            due = t.get("due_ts")
            due_str = f" (due {due})" if due else ""
            lines.append(f"{i}. [{t.get('status', 'todo')}] {t.get('text', '')}{due_str}")
        return "\n".join(lines)

    return await asyncio.to_thread(_run)


async def run_stdio() -> None:
    """Runs this server over stdio until the client disconnects — what
    `mcp_server_main.py` calls into. Kept separate from module-level
    execution so the module can be imported (e.g. for tests) without
    side effects."""
    await mcp.run_stdio_async()
