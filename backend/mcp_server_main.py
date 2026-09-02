#!/usr/bin/env python3
"""Standalone entrypoint for Zenith's MCP server. This is what an MCP
client config (e.g. Claude Desktop's `claude_desktop_config.json`) should
point its `command`/`args` at directly — it does not start or depend on
the FastAPI backend (`main.py`); it only needs `CORTEX_DATA_DIR` set to
find the same SQLite database the main app uses. See the
"Exposing Zenith as an MCP server" section of README.md for a full
Claude Desktop config example.

Run directly (mainly for manual testing):
    CORTEX_DATA_DIR=/path/to/data .venv/bin/python mcp_server_main.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure `app` is importable regardless of the working directory this
# script is launched from (MCP clients typically spawn it with an
# arbitrary cwd, not necessarily this backend/ directory).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.mcp_server import run_stdio  # noqa: E402


if __name__ == "__main__":
    asyncio.run(run_stdio())
