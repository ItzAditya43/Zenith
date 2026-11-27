"""MCP per-tool policy: off hides a tool, auto makes it run without asking,
env values are never listed."""
from __future__ import annotations

import asyncio

from app.services import agent_service, mcp_service


def test_policy_controls_visibility_and_risk(client, monkeypatch):
    s = mcp_service.add_server("files", "echo", [], {"API_KEY": "sk-live-123"})
    listed = client.get("/api/mcp/servers").json()[0]
    assert listed["env"] == {"API_KEY": "********"}

    async def fake_tools(server):
        return [{"name": "read", "description": "", "input_schema": {}}, {"name": "wipe", "description": "", "input_schema": {}}]

    monkeypatch.setattr(mcp_service, "list_tools", fake_tools)
    names = [t["agent_tool_name"] for t in asyncio.run(mcp_service.list_all_tools())]
    assert names == ["mcp__files__read", "mcp__files__wipe"]
    assert agent_service.classify_risk("mcp__files__read", {}) == "risky"  # default: ask

    assert client.put(f"/api/mcp/servers/{s['id']}/tools/read/policy", json={"policy": "auto"}).status_code == 200
    assert client.put(f"/api/mcp/servers/{s['id']}/tools/wipe/policy", json={"policy": "off"}).status_code == 200
    assert client.put(f"/api/mcp/servers/{s['id']}/tools/wipe/policy", json={"policy": "yolo"}).status_code == 400
    assert agent_service.classify_risk("mcp__files__read", {}) == "safe"
    names = [t["agent_tool_name"] for t in asyncio.run(mcp_service.list_all_tools())]
    assert names == ["mcp__files__read"]


def test_connection_check_is_recorded(client, monkeypatch):
    s = mcp_service.add_server("broken", "definitely-not-a-binary-xyz", [])

    async def boom(server):
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(mcp_service, "_list_tools_raw", boom)
    assert client.get(f"/api/mcp/servers/{s['id']}/tools").status_code == 502
    row = mcp_service.get_server(s["id"])
    assert row["last_check_ok"] == 0 and "spawn failed" in row["last_error"]
