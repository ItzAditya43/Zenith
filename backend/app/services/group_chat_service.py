"""Simulated multi-bot group chat: a conversation bound to several
personas instead of one. Each persona takes a turn in sequence, seeing
the real conversation history *plus* what the other personas already
said this round — so they can react to each other, not just to the user.
"""
from __future__ import annotations

import re
from typing import AsyncIterator

from app.core.logging import get_logger
from app.db import storage
from app.services import persona_service
from app.services.ollama_client import OllamaClient, OllamaError
from app.services.router import ModelRegistry, ModelRouter

log = get_logger(__name__)


async def run_group_turn(
    conversation_id: str, user_text: str, persona_ids: list[str]
) -> AsyncIterator[dict]:
    """Yields {"type": "speaker_start"|"token"|"speaker_done"|"error"|"done", ...}
    — one full response per persona, run sequentially, each with the
    whole conversation history plus this round's earlier replies appended
    so personas can address each other."""
    personas = [persona_service.get_persona(pid) for pid in persona_ids]
    personas = [p for p in personas if p]
    if not personas:
        yield {"type": "error", "message": "No valid personas set for this group chat."}
        return

    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    model = router._match_capability("general", installed) or (installed[0] if installed else None)  # noqa: SLF001
    if not model:
        yield {"type": "error", "message": "No local model available."}
        return

    history = storage.get_messages(conversation_id)
    parent_for_user = storage.get_last_active_message_id(conversation_id)
    user_msg = storage.add_message(conversation_id, "user", user_text, parent_id=parent_for_user)
    parent_id = user_msg["id"]

    client = OllamaClient()
    round_so_far: list[tuple[str, str]] = []  # (persona name, text) said this round

    for persona in personas:
        yield {"type": "speaker_start", "persona_id": persona["id"], "persona_name": persona["name"]}
        transcript = "\n".join(f"{name}: {text}" for name, text in round_so_far)
        messages = [{"role": "system", "content": persona["system_prompt"]}]
        messages += [{"role": m["role"], "content": m["content"]} for m in history[-16:]]
        prompt = user_text
        if transcript:
            prompt += f"\n\n(So far in this round, others have said:\n{transcript}\n\nRespond as {persona['name']}.)"
        messages.append({"role": "user", "content": prompt})

        try:
            reply = await client.chat(model, messages)
        except OllamaError as exc:
            yield {"type": "error", "message": f"{persona['name']}: {exc}"}
            continue

        for chunk in re.findall(r"\S+\s*", reply):
            yield {"type": "token", "persona_id": persona["id"], "text": chunk}

        saved = storage.add_message(
            conversation_id, "assistant", reply, model=model,
            parent_id=parent_id, speaker_persona_id=persona["id"],
        )
        parent_id = saved["id"]
        round_so_far.append((persona["name"], reply))
        yield {"type": "speaker_done", "persona_id": persona["id"], "message_id": saved["id"], "text": reply}

    yield {"type": "done", "parent_id": parent_id}
