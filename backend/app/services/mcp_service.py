"""MCP (Model Context Protocol) client support — lets agent mode call
tools from external MCP servers, not just the built-in bash/file/web
set. Servers run as local subprocesses over stdio (the standard way to
run MCP servers locally — no hosted/paid MCP service involved, same
"free by construction" posture as everything else in Zenith).

Each server is configured once (command + args + env) in Settings.
Connections are stateless-per-call: a fresh stdio subprocess is spawned,
used, and torn down for each list_tools/call_tool. Simpler and safer
than managing long-lived subprocess lifecycles inside a web server
(no orphaned processes if the backend restarts mid-session), at the
cost of per-call subprocess-spawn latency — acceptable for the
few-calls-per-turn workload this feeds into.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

# Tool names exposed to the agent loop are prefixed so they can't collide
# with the built-in tool set and so the loop knows to route them here.
TOOL_PREFIX = "mcp__"

# Spawning a subprocess and completing MCP's initialize handshake is not
# instant — cap it so one unresponsive server can't hang an entire turn.
_CONNECT_TIMEOUT = 15.0
_CALL_TIMEOUT = 60.0


def list_servers() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM mcp_servers ORDER BY created_at ASC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["args"] = json.loads(d["args"])
            d["env"] = json.loads(d["env"])
            out.append(d)
        return out


def get_server(server_id: str) -> dict | None:
    for s in list_servers():
        if s["id"] == server_id:
            return s
    return None


def add_server(name: str, command: str, args: list[str] | None = None,
                env: dict[str, str] | None = None) -> dict:
    sid = str(uuid.uuid4())
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO mcp_servers (id, name, command, args, env, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (sid, name.strip(), command.strip(), json.dumps(args or []), json.dumps(env or {}), now),
        )
    return {"id": sid, "name": name.strip(), "command": command.strip(),
            "args": args or [], "env": env or {}, "enabled": 1, "created_at": now}


def remove_server(server_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,))


def set_enabled(server_id: str, enabled: bool) -> None:
    with _conn() as conn:
        conn.execute("UPDATE mcp_servers SET enabled = ? WHERE id = ?", (1 if enabled else 0, server_id))


async def _with_session(server: dict, fn):
    """Connects to `server` over stdio, runs `fn(session)`, and always
    tears the subprocess down cleanly afterward — including on error or
    timeout, so a bad server config can't leak processes."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=server["command"], args=server.get("args") or [], env=server.get("env") or None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=_CONNECT_TIMEOUT)
            return await fn(session)


async def _list_tools_raw(server: dict) -> list[dict]:
    """Connects and lists tools, raising on any failure — the honest
    version. `list_tools` below wraps this to swallow errors for the
    agent-loop discovery path; the Settings "check this server" health
    check calls this one directly so a broken config actually surfaces
    an error instead of an indistinguishable empty list."""
    async def _list(session):
        result = await session.list_tools()
        return [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in result.tools
        ]
    return await asyncio.wait_for(_with_session(server, _list), timeout=_CONNECT_TIMEOUT + 5)


async def list_tools(server: dict) -> list[dict]:
    """Returns [{name, description, input_schema}] for one server.
    Empty list (logged, not raised) if the server fails to start or
    doesn't respond in time — one bad MCP server shouldn't block agent
    mode from using the others. See `_list_tools_raw` for the version
    that raises, used by the Settings UI health check."""
    try:
        return await _list_tools_raw(server)
    except Exception as exc:
        log.warning("mcp.list_tools_failed", server=server["name"], error=str(exc))
        return []


async def list_all_tools() -> list[dict]:
    """Tools from every enabled server, each tagged with its prefixed
    agent-loop name (mcp__<server>__<tool>) and originating server id."""
    out: list[dict] = []
    for server in list_servers():
        if not server["enabled"]:
            continue
        for t in await list_tools(server):
            out.append({
                "agent_tool_name": f"{TOOL_PREFIX}{server['name']}__{t['name']}",
                "server_id": server["id"],
                "server_name": server["name"],
                "tool_name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            })
    return out


async def call_tool(server: dict, tool_name: str, arguments: dict, max_chars: int = 4000) -> str:
    """Calls one tool on one server, returns its text output (MCP tool
    results can carry multiple content blocks — text ones are joined;
    non-text blocks are summarized by type since agent mode's loop is
    text-only)."""
    try:
        async def _call(session):
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments), timeout=_CALL_TIMEOUT
            )
            parts = []
            for block in result.content:
                if getattr(block, "text", None) is not None:
                    parts.append(block.text)
                else:
                    parts.append(f"[{getattr(block, 'type', 'non-text content')}]")
            text = "\n".join(parts)
            if result.isError:
                text = f"Error: {text}"
            return text[:max_chars]
        return await _with_session(server, _call)
    except asyncio.TimeoutError:
        return f"Error: MCP tool call to {server['name']}/{tool_name} timed out."
    except Exception as exc:
        log.warning("mcp.call_tool_failed", server=server["name"], tool=tool_name, error=str(exc))
        return f"Error calling {server['name']}/{tool_name}: {exc}"


def parse_agent_tool_name(agent_tool_name: str) -> tuple[str, str] | None:
    """Splits "mcp__<server>__<tool>" back into (server_name, tool_name),
    or None if it doesn't match the expected shape."""
    if not agent_tool_name.startswith(TOOL_PREFIX):
        return None
    rest = agent_tool_name[len(TOOL_PREFIX):]
    if "__" not in rest:
        return None
    server_name, tool_name = rest.split("__", 1)
    return server_name, tool_name
