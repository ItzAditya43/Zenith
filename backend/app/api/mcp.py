"""MCP server configuration + tool discovery for agent mode.

  GET    /api/mcp/servers            — list configured servers
  POST   /api/mcp/servers            — add {name, command, args?, env?}
  PATCH  /api/mcp/servers/{id}       — enable/disable
  DELETE /api/mcp/servers/{id}       — remove
  GET    /api/mcp/servers/{id}/tools — connect now and list what it offers (health check)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.models.schemas import MCPServerCreate, MCPServerToggle
from app.services import mcp_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/servers")
async def list_servers():
    return mcp_service.list_servers()


@router.post("/servers")
async def add_server(body: MCPServerCreate):
    return mcp_service.add_server(body.name, body.command, body.args, body.env)


@router.patch("/servers/{server_id}")
async def toggle_server(server_id: str, body: MCPServerToggle):
    if not mcp_service.get_server(server_id):
        raise HTTPException(404, "No such MCP server.")
    mcp_service.set_enabled(server_id, body.enabled)
    return {"ok": True}


@router.delete("/servers/{server_id}")
async def remove_server(server_id: str):
    mcp_service.remove_server(server_id)
    return {"ok": True}


@router.get("/servers/{server_id}/tools")
async def get_server_tools(server_id: str):
    """Connects to the server right now and lists its tools — also
    serves as a quick "does this config actually work" health check
    from the Settings UI."""
    server = mcp_service.get_server(server_id)
    if not server:
        raise HTTPException(404, "No such MCP server.")
    return await mcp_service.list_tools(server)
