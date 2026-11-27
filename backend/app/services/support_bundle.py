"""Diagnostic bundle for bug reports — what's needed to understand a
problem, and nothing personal.

Includes: app/API version, platform, Python, database schema state,
Ollama version and installed model names, component health, config with
every secret and personal field removed, and the tail of the app log
with emails, tokens, keys and the home directory path scrubbed.

Never includes: conversations, memories, documents, attachments, the
database itself, API keys, passwords or provider credentials.

`preview()` returns exactly the files that `build_zip()` would write, so
the Settings screen can show the user every line before they download.
"""
from __future__ import annotations

import io
import json
import platform
import re
import sys
import time
import zipfile
from pathlib import Path

from app.core.config import data_dir, db_path, profile_name, settings
from app.core.security import redact_config

LOG_LINES = 400
_SECRETISH = re.compile(r"(key|token|secret|password|pass|auth|cookie|webhook|topic|email|imap|smtp|user)", re.I)
_SCRUB = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"\b(sk|pk|rk|whsec|zk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{8,}"), "<secret>"),
    (re.compile(r"(?i)(bearer|authorization|api[_-]?key|token|password|secret)([\"':= ]+)([^\s\"',}]{6,})"), r"\1\2<redacted>"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "<hex>"),
]


def scrub(text: str) -> str:
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    for pat, rep in _SCRUB:
        text = pat.sub(rep, text)
    return text


def _config() -> dict:
    out = {}
    for k, v in redact_config(dict(settings.all())).items():
        if _SECRETISH.search(k) and not isinstance(v, bool):
            out[k] = "<set>" if v else "<empty>"
        elif isinstance(v, str):
            out[k] = scrub(v)
        else:
            out[k] = v
    return out


def _schema() -> dict:
    import sqlite3

    from app.db.migrations import MIGRATIONS
    latest = max(v for v, _, _ in MIGRATIONS)
    try:
        conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT version, name, applied_at FROM schema_version ORDER BY version DESC LIMIT 5").fetchall()
            size = db_path().stat().st_size
        finally:
            conn.close()
        current = rows[0][0] if rows else 0
        return {"current": current, "latest_known": latest, "up_to_date": current >= latest,
                "recent": [{"version": r[0], "name": r[1], "applied_at": r[2]} for r in rows], "db_bytes": size}
    except Exception as exc:  # noqa: BLE001
        return {"error": scrub(str(exc)), "latest_known": latest}


async def _ollama() -> dict:
    import httpx

    from app.services.ollama_client import OllamaClient

    client = OllamaClient()
    out: dict = {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"{client.host}/api/version")
            out["version"] = r.json().get("version")
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"not reachable: {type(exc).__name__}"
    try:
        models = await client.list_models()
        out["models"] = sorted(m.get("name", "?") for m in models)
    except Exception:  # noqa: BLE001
        out.setdefault("models", [])
    return out


def _log_tail() -> str:
    path = data_dir() / "zenith.log"
    if not path.exists():
        return "(no log file yet)\n"
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 400_000))
        lines = fh.read().decode(errors="replace").splitlines()[-LOG_LINES:]
    return scrub("\n".join(lines)) + "\n"


async def preview(health: dict | None = None) -> dict[str, str]:
    from app.core.security import API_VERSION
    from app.main import app as _app

    info = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "app_version": _app.version,
        "api_version": API_VERSION,
        "profile": profile_name(),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
                     "python": sys.version.split()[0], "frozen": bool(getattr(sys, "frozen", False))},
        "database": _schema(),
        "ollama": await _ollama(),
    }
    files = {
        "system.json": json.dumps(info, indent=2, default=str),
        "config.redacted.json": json.dumps(_config(), indent=2, default=str),
        "zenith.log.tail.txt": _log_tail(),
    }
    if health is not None:
        files["health.json"] = scrub(json.dumps(health, indent=2, default=str))
    files["README.txt"] = (
        "Zenith diagnostic bundle\n\nContains version/platform info, database schema state, Ollama version and model\n"
        "names, component health, settings with secrets and personal fields removed, and the last\n"
        f"{LOG_LINES} log lines with emails, tokens and your home path scrubbed.\n\n"
        "It does NOT contain conversations, memories, documents, attachments, the database,\n"
        "API keys or passwords. Read every file before sharing it.\n"
    )
    return files


def build_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()
