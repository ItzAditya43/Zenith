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


_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
_RUNNERS = {"npm": "npx", "pypi": "uvx"}


def _registry_entry(item: dict) -> dict | None:
    """Map one MCP registry record to an installable local (stdio) server,
    or None when it only ships as a remote/docker server."""
    srv = item.get("server") or item
    for pkg in srv.get("packages") or []:
        runner = _RUNNERS.get(pkg.get("registryType", ""))
        if not runner or (pkg.get("transport") or {}).get("type", "stdio") != "stdio":
            continue
        args = ["-y", pkg["identifier"]] if runner == "npx" else [pkg["identifier"]]
        args += [str(a["value"]) for a in pkg.get("packageArguments") or [] if a.get("type") == "positional" and a.get("value")]
        return {
            "name": srv.get("name", pkg["identifier"]).rsplit("/", 1)[-1],
            "full_name": srv.get("name"),
            "description": (srv.get("description") or "")[:300],
            "repository": (srv.get("repository") or {}).get("url"),
            "command": runner,
            "args": args,
            "env": [
                {"name": e["name"], "required": bool(e.get("isRequired")), "description": e.get("description", "")}
                for e in pkg.get("environmentVariables") or [] if e.get("name")
            ],
        }
    return None


@router.get("/registry")
async def search_registry(q: str = "", limit: int = 20):
    """Search the official MCP registry for servers that run locally."""
    import httpx

    limit = max(1, min(limit, 50))
    params: dict[str, str | int] = {"limit": 100}  # many entries are remote-only; filter below
    if q.strip():
        params["search"] = q.strip()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_REGISTRY, params=params)
            resp.raise_for_status()
            items = resp.json().get("servers") or []
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"MCP registry unavailable: {exc}") from exc
    seen: set[str] = set()
    out = []
    for item in items:
        entry = _registry_entry(item)
        if entry and entry["full_name"] not in seen:
            seen.add(entry["full_name"])
            out.append(entry)
    return out[:limit]


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
    from the Settings UI. Unlike the agent loop's tool discovery (which
    swallows a bad server's errors so one broken config doesn't block
    the others), this surfaces the real connection error so a user
    testing a new server config actually finds out it's broken instead
    of just seeing an empty tool list with no explanation."""
    server = mcp_service.get_server(server_id)
    if not server:
        raise HTTPException(404, "No such MCP server.")
    try:
        return await mcp_service._list_tools_raw(server)
    except Exception as exc:
        raise HTTPException(502, f"Couldn't connect to '{server['name']}': {exc}") from exc
