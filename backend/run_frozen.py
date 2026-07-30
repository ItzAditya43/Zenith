"""Entry point for the PyInstaller-frozen backend (see cortex-backend.spec).

Runs the same FastAPI app the Docker image does, but as a standalone binary the
desktop shell launches as a sidecar. The port is fixed so the Tauri front end
knows where to reach it; CORTEX_DATA_DIR should be set by the shell to the
platform's app-data directory before launch.
"""
import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("CORTEX_PORT", "8420"))
    # 127.0.0.1 only by default — a desktop app's backend shouldn't be exposed
    # to the network unless the user deliberately opts into LAN access.
    host = os.environ.get("CORTEX_BIND", "127.0.0.1")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
