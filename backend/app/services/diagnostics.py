"""Fast per-file checks after an agent edit, so mistakes come back at once.

Not a language server: it runs whichever quick checker is available for
the file type and reports errors only (not style), capped to a few lines.
The point is to catch the edit that broke the file (a syntax error, an
undefined name) on the very next step, instead of after a full test run,
or never if there are no tests.

  .py           ruff (errors only: syntax, undefined names, bad imports)
                if installed, else Python's own compile check
  .js .mjs .cjs node --check
  .go           gofmt -e (syntax)
  .json         parsed with json.loads

Anything else, or a missing tool, gives no diagnostics (never an error).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

MAX_LINES = 8
TIMEOUT = 15.0
# Ruff rule families that are real errors rather than style.
_RUFF_SELECT = "E9,F63,F7,F82,F821,F822,F823,F401"


async def _run(argv: list[str], cwd: Path) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except (FileNotFoundError, PermissionError):
        return 0, ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 0, ""
    return proc.returncode or 0, out.decode(errors="replace")


def _cap(lines: list[str]) -> list[str]:
    lines = [ln.rstrip() for ln in lines if ln.strip()]
    if len(lines) > MAX_LINES:
        return lines[:MAX_LINES] + [f"… {len(lines) - MAX_LINES} more"]
    return lines


async def _python(path: Path, rel: str) -> list[str]:
    ruff = shutil.which("ruff")
    if ruff:
        code, out = await _run([ruff, "check", "--no-cache", "--output-format=json", "--select", _RUFF_SELECT, str(path)], path.parent)
        try:
            items = json.loads(out or "[]")
        except json.JSONDecodeError:
            items = None
        if isinstance(items, list):
            return _cap([
                f"{rel}:{i.get('location', {}).get('row', '?')}: {i.get('code') or 'error'} {i.get('message', '')}"
                for i in items
            ])
    code, out = await _run([sys.executable, "-c",
                            "import sys,ast; ast.parse(open(sys.argv[1], encoding='utf-8').read(), sys.argv[1])",
                            str(path)], path.parent)
    if code == 0:
        return []
    last = [ln for ln in out.splitlines() if ln.strip()]
    line_no = next((ln.split("line ")[-1].split(",")[0].strip() for ln in last if "line " in ln), "?")
    msg = last[-1] if last else "syntax error"
    return [f"{rel}:{line_no}: {msg}"]


async def _javascript(path: Path, rel: str) -> list[str]:
    node = shutil.which("node")
    if not node:
        return []
    code, out = await _run([node, "--check", str(path)], path.parent)
    if code == 0:
        return []
    lines = [ln for ln in out.splitlines() if ln.strip()]
    loc = next((ln for ln in lines if str(path) in ln), "")
    line_no = loc.rsplit(":", 1)[-1] if loc else "?"
    err = next((ln for ln in lines if "Error" in ln), lines[-1] if lines else "syntax error")
    return [f"{rel}:{line_no}: {err.strip()}"]


async def _go(path: Path, rel: str) -> list[str]:
    gofmt = shutil.which("gofmt")
    if not gofmt:
        return []
    code, out = await _run([gofmt, "-e", "-l", str(path)], path.parent)
    if code == 0:
        return []
    return _cap([ln.replace(str(path), rel) for ln in out.splitlines()])


def _json(path: Path, rel: str) -> list[str]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return []
    except json.JSONDecodeError as exc:
        return [f"{rel}:{exc.lineno}: invalid JSON: {exc.msg}"]
    except (OSError, UnicodeDecodeError):
        return []


async def check_file(path: Path, rel: str) -> list[str]:
    """Problems found in one file, as "path:line: message" strings."""
    if not path.is_file():
        return []
    ext = path.suffix.lower()
    try:
        if ext == ".py":
            return await _python(path, rel)
        if ext in (".js", ".mjs", ".cjs"):
            return await _javascript(path, rel)
        if ext == ".go":
            return await _go(path, rel)
        if ext == ".json":
            return _json(path, rel)
    except Exception:
        return []
    return []


def format_for_model(problems: list[str]) -> str:
    if not problems:
        return ""
    return ("\n\nProblems found in the file after this edit (fix these before moving on):\n"
            + "\n".join(f"- {p}" for p in problems))
