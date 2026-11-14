"""Models Ollama has refused to run, so routing can stop sending to them.

A pinned Ollama Cloud model can stop working without anything changing in
Zenith: Ollama retires it (HTTP 410) or starts asking for paid credits
(402). Without this, every message would go to the pinned model, fail,
and fall back to whatever the fallback role resolves to — often the same
dead pin. Here a refusal is remembered for a while; the router skips the
model and Settings shows why.

In memory only: a restart, or re-pinning the model in Settings, clears it,
so buying credits or pulling the model again takes effect immediately.
"""
from __future__ import annotations

import re
import time

TTL_SECONDS = 30 * 60

# status -> short reason shown in Settings
_REASONS = {
    402: "needs Ollama credits or a subscription",
    404: "not installed in Ollama",
    410: "retired by Ollama",
}
_STATUS_RE = re.compile(r"Ollama returned (\d{3}) for model")

_dead: dict[str, tuple[float, int, str]] = {}  # model -> (since, status, reason)


def note_error(model: str, message: str) -> None:
    """Record `model` as unavailable if `message` (an OllamaError text) is a
    refusal that won't fix itself on retry. Other errors are ignored."""
    m = _STATUS_RE.search(message or "")
    if not m:
        return
    status = int(m.group(1))
    if status in _REASONS:
        _dead[model] = (time.time(), status, _REASONS[status])


def is_unavailable(model: str | None) -> bool:
    if not model:
        return False
    entry = _dead.get(model)
    if entry is None:
        return False
    if time.time() - entry[0] > TTL_SECONDS:
        _dead.pop(model, None)
        return False
    return True


def unavailable() -> dict[str, dict]:
    """{model: {"status": 402, "reason": "..."}} for models still marked."""
    return {name: {"status": status, "reason": reason}
            for name, (_, status, reason) in list(_dead.items()) if is_unavailable(name)}


def clear(model: str | None = None) -> None:
    if model is None:
        _dead.clear()
    else:
        _dead.pop(model, None)
