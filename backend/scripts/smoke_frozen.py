"""Smoke-test the frozen backend (dist/zenith-backend[.exe]): start it on a
spare port with a throwaway data dir, wait for the API, and fail unless
sqlite-vec loaded (vector search silently disappeared from frozen builds
before). Portable — the same check on Windows, macOS and Linux.

    python scripts/smoke_frozen.py [path-to-binary]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PORT = 8499


def main() -> int:
    here = Path(__file__).resolve().parent.parent
    binary = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "dist" / "zenith-backend"
    if not binary.exists() and binary.with_suffix(".exe").exists():
        binary = binary.with_suffix(".exe")
    data = tempfile.mkdtemp(prefix="zenith-smoke-")
    env = {**os.environ, "ZENITH_DATA_DIR": data, "ZENITH_PORT": str(PORT), "ZENITH_BIND": "127.0.0.1"}
    log = open(Path(data) / "backend.log", "w+")
    proc = subprocess.Popen([str(binary)], env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        status = None
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/rag/status", timeout=10) as r:
                    status = json.load(r)
                    break
            except Exception:
                time.sleep(2)
        print("rag status:", json.dumps(status))
        if status and status.get("vector_extension") is True:
            print("OK: frozen backend serves the API and sqlite-vec is loaded")
            return 0
        print("FAIL: " + ("backend exited early" if proc.poll() is not None else
                          "sqlite-vec not loaded" if status else "API never answered"))
        log.flush()
        log.seek(0)
        print("".join(log.readlines()[-40:]))
        return 1
    finally:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
