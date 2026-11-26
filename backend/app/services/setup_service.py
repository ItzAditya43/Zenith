"""First-run readiness and the optional "Get started" checklist.

`readiness()` answers "can I chat yet, and if not, what exactly do I do?"
— backend, a usable model (local Ollama or an API provider), free disk
space, and ffmpeg (only needed for video) — with copyable, per-platform
fixes. Nothing here is required to start: the checklist is a set of
optional next steps the user can skip or hide for good.
"""
from __future__ import annotations

import platform
import shutil

from app.core.config import data_dir
from app.db.storage import _conn

INSTALL_OLLAMA = {
    "Linux": "curl -fsSL https://ollama.com/install.sh | sh",
    "Darwin": "brew install ollama   # or download the app from https://ollama.com/download",
    "Windows": "winget install Ollama.Ollama",
}
START_OLLAMA = {
    "Linux": "ollama serve   # or: systemctl --user start ollama",
    "Darwin": "open -a Ollama",
    "Windows": "Start the Ollama app from the Start menu",
}
INSTALL_FFMPEG = {
    "Linux": "sudo apt install ffmpeg   # Fedora: sudo dnf install ffmpeg · Arch: sudo pacman -S ffmpeg",
    "Darwin": "brew install ffmpeg",
    "Windows": "winget install Gyan.FFmpeg",
}


def _os() -> str:
    s = platform.system()
    return s if s in ("Linux", "Darwin", "Windows") else "Linux"


async def readiness() -> dict:
    from app.services import providers
    from app.services.ollama_client import OllamaClient, OllamaError

    os_name = _os()
    checks: list[dict] = []

    ollama_ok, local_models = False, []
    try:
        names = [m["name"] for m in await OllamaClient()._ollama_models()]  # noqa: SLF001 — Ollama only, not providers
        ollama_ok = True
        local_models = [n for n in names if "embed" not in n.lower() and not n.lower().endswith(("cloud", "-cloud"))]
    except (OllamaError, Exception):  # noqa: BLE001
        pass
    enabled_providers = [p for p in providers.list_public() if p.get("enabled")]

    checks.append({"id": "backend", "label": "Zenith's engine", "ok": True, "detail": "Running"})
    if ollama_ok:
        checks.append({"id": "ollama", "label": "Ollama", "ok": True, "detail": "Running on this machine"})
    else:
        installed = shutil.which("ollama") is not None
        checks.append({
            "id": "ollama", "label": "Ollama", "ok": False, "optional": bool(enabled_providers),
            "detail": "Installed but not running" if installed else "Not installed",
            "fix": START_OLLAMA[os_name] if installed else INSTALL_OLLAMA[os_name],
            "why": "Ollama runs AI models on this machine. You can skip it and use an API provider instead.",
        })
    has_model = bool(local_models) or bool(enabled_providers)
    checks.append({
        "id": "model", "label": "A model to chat with", "ok": has_model,
        "detail": (f"{len(local_models)} local" if local_models else "") + (
            f"{' · ' if local_models else ''}{len(enabled_providers)} provider{'s' if len(enabled_providers) != 1 else ''}" if enabled_providers else ""
        ) or "None yet",
        "fix": "" if has_model else ("ollama pull llama3.2:3b   # small and quick; or browse Settings → Installed models" if ollama_ok else ""),
        "why": "" if has_model else "Download one from Settings → Installed models, or connect an API provider in Settings → Providers.",
    })
    free_gb = shutil.disk_usage(data_dir()).free / 1e9
    checks.append({"id": "disk", "label": "Free disk space", "ok": free_gb >= 5, "optional": True,
                   "detail": f"{free_gb:.0f} GB free", "why": "" if free_gb >= 5 else "Models are several GB each; free up space before downloading more."})
    ff = shutil.which("ffmpeg") is not None
    checks.append({"id": "ffmpeg", "label": "ffmpeg (for video)", "ok": ff, "optional": True,
                   "detail": "Installed" if ff else "Not installed — only needed to read videos",
                   "fix": "" if ff else INSTALL_FFMPEG[os_name]})
    ready = has_model
    return {"ready_to_chat": ready, "os": os_name, "checks": checks}


def progress() -> dict:
    """Which optional first steps are done, from what's actually in the database."""
    def one(sql: str) -> bool:
        try:
            with _conn() as conn:
                return conn.execute(sql).fetchone() is not None
        except Exception:  # noqa: BLE001 — a missing table just means "not yet"
            return False

    from app.core.config import settings

    return {
        "chatted": one("SELECT 1 FROM messages WHERE role = 'assistant' LIMIT 1"),
        "file": one("SELECT 1 FROM attachments LIMIT 1"),
        "research": one("SELECT 1 FROM research_reports LIMIT 1"),
        "agent": bool(settings.get("agent_enabled")) and one("SELECT 1 FROM tool_calls LIMIT 1"),
        "memory": one("SELECT 1 FROM memories LIMIT 1"),
    }
