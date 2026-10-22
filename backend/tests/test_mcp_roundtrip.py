"""End-to-end MCP: Zenith's own MCP client (mcp_service) talking over real
stdio to Zenith's own MCP server (mcp_server_main.py) — both halves of the
`mcp` library integration, with no mocks, against a temp database."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def zenith_server(temp_data_dir):
    from app.db.storage import init_db

    init_db()
    return {
        "id": "self",
        "name": "zenith",
        "command": sys.executable,
        "args": [str(BACKEND_ROOT / "mcp_server_main.py")],
        "env": {"ZENITH_DATA_DIR": str(temp_data_dir), "PATH": "/usr/bin:/bin"},
        "enabled": True,
    }


async def test_list_tools_over_stdio(zenith_server):
    from app.services import mcp_service

    tools = await mcp_service._list_tools_raw(zenith_server)
    names = {t["name"] for t in tools}
    assert {"zenith_memory_search", "zenith_notes_list", "zenith_todos_list"} <= names
    memory = next(t for t in tools if t["name"] == "zenith_memory_search")
    assert memory["description"]
    assert "query" in memory["input_schema"]["properties"]


async def test_call_tool_reads_the_shared_database(zenith_server):
    from app.services import mcp_service
    from app.services.memory_service import add_memory

    add_memory("Prefers tabs over spaces in Go code")
    out = await mcp_service.call_tool(zenith_server, "zenith_memory_search", {"query": "tabs"})
    assert "Prefers tabs over spaces" in out
    out = await mcp_service.call_tool(zenith_server, "zenith_memory_search", {"query": "nonexistent-xyz"})
    assert "No memories found" in out


async def test_unknown_tool_is_reported_not_raised(zenith_server):
    from app.services import mcp_service

    out = await mcp_service.call_tool(zenith_server, "does_not_exist", {})
    assert out.startswith("Error")


async def test_broken_server_command_degrades_to_empty_list(temp_data_dir):
    from app.services import mcp_service

    bad = {"id": "x", "name": "broken", "command": "/nonexistent/binary", "args": [], "enabled": True}
    assert await mcp_service.list_tools(bad) == []
    with pytest.raises((OSError, BaseExceptionGroup)):
        await mcp_service._list_tools_raw(bad)


def test_agent_tool_name_round_trip():
    from app.services import mcp_service

    assert mcp_service.parse_agent_tool_name("mcp__zenith__zenith_notes_list") == ("zenith", "zenith_notes_list")
    assert mcp_service.parse_agent_tool_name("bash") is None
    assert mcp_service.parse_agent_tool_name("mcp__nounderscore") is None
