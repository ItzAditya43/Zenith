"""Run a command with a wall-clock limit and kill its whole process tree on
timeout — portable replacement for coreutils `timeout`, which macOS lacks.
PyInstaller spawns helper subprocesses; killing only the parent would leave
them holding files open for the next attempt.

    python scripts/run_with_timeout.py SECONDS cmd [args...]
Exit code: the command's own, or 124 on timeout (like `timeout`).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys


def main() -> int:
    limit = float(sys.argv[1])
    cmd = sys.argv[2:]
    if os.name == "nt":
        proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        proc = subprocess.Popen(cmd, start_new_session=True)
    try:
        return proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        print(f"timed out after {limit:.0f}s — killing process tree", flush=True)
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
