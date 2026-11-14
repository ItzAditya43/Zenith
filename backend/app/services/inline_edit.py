"""Inline edit: rewrite a selected range of a file from a short instruction.

Lighter than an agent turn: one model call, no tools, nothing written to
disk. The result goes back to the editor as a proposed replacement, shown
as a diff the user applies or discards (and then saves as usual).
"""
from __future__ import annotations

import re

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

CONTEXT_LINES = 60
MAX_SELECTION_LINES = 400
_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)


class InlineEditError(RuntimeError):
    pass


async def pick_model() -> str:
    from app.services import model_health
    from app.services.router import ModelRegistry, ModelRouter, is_cloud_model

    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    for role in ("code", "general"):
        m = router._match_capability(role, installed)  # noqa: SLF001
        if not m or model_health.is_unavailable(m):
            continue
        pinned = (settings.get("model_overrides") or {}).get(role) == m
        if is_cloud_model(m) and not pinned and not settings.get("route_to_cloud_models", False):
            continue
        return m
    raise InlineEditError("No model is available for code edits. Pull one (e.g. a qwen coder model) or pin one in Settings → Model routing.")


def _extract(reply: str) -> str:
    m = _FENCE.search(reply or "")
    text = m.group(1) if m else (reply or "")
    return text.rstrip("\n")


def _reindent(new: str, old: str) -> str:
    """If the model dropped the selection's common indentation, put it back."""
    def indent_of(s: str) -> str:
        lines = [ln for ln in s.splitlines() if ln.strip()]
        if not lines:
            return ""
        prefix = re.match(r"[ \t]*", lines[0]).group(0)  # type: ignore[union-attr]
        for ln in lines[1:]:
            while prefix and not ln.startswith(prefix):
                prefix = prefix[:-1]
        return prefix

    want, have = indent_of(old), indent_of(new)
    if want and not have:
        return "\n".join((want + ln) if ln.strip() else ln for ln in new.splitlines())
    return new


async def rewrite(path: str, content: str, from_line: int, to_line: int, instruction: str) -> dict:
    """Returns {"model", "original", "replacement"} for lines
    from_line..to_line (1-based, inclusive)."""
    lines = content.splitlines()
    if not (1 <= from_line <= to_line <= max(len(lines), 1)):
        raise InlineEditError("The selected lines are outside the file.")
    if to_line - from_line + 1 > MAX_SELECTION_LINES:
        raise InlineEditError(f"Select at most {MAX_SELECTION_LINES} lines for an inline edit; use agent mode for bigger changes.")
    instruction = (instruction or "").strip()
    if not instruction:
        raise InlineEditError("Say what to change.")
    original = "\n".join(lines[from_line - 1:to_line])
    before = "\n".join(lines[max(0, from_line - 1 - CONTEXT_LINES):from_line - 1])
    after = "\n".join(lines[to_line:to_line + CONTEXT_LINES])
    model = await pick_model()
    prompt = (
        f"You are editing part of the file `{path}`.\n\n"
        f"Code just before the selection (for context, do not repeat it):\n```\n{before}\n```\n\n"
        f"THE SELECTION (lines {from_line}-{to_line}):\n```\n{original}\n```\n\n"
        f"Code just after the selection (for context, do not repeat it):\n```\n{after}\n```\n\n"
        f"Instruction: {instruction}\n\n"
        "Rewrite only THE SELECTION to follow the instruction. Keep the same indentation and "
        "style as the surrounding code. Reply with the replacement code in a single fenced code "
        "block and nothing else."
    )
    from app.services.ollama_client import OllamaClient, OllamaError

    try:
        reply = await OllamaClient().chat(model, [{"role": "user", "content": prompt}], options={"temperature": 0.2})
    except OllamaError as exc:
        raise InlineEditError(str(exc)) from exc
    replacement = _reindent(_extract(reply), original)
    if not replacement.strip() and original.strip():
        raise InlineEditError("The model returned nothing usable. Try rephrasing the instruction.")
    log.info("inline_edit.done", model=model, lines=to_line - from_line + 1)
    return {"model": model, "original": original, "replacement": replacement}
