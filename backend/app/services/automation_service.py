"""User-defined trigger -> action rules on top of the same event bus
webhooks use (see events.py) — "when a file lands in my inbox folder,
summarize it" without hand-writing a schedule prompt or standing up a
webhook receiver.

Trigger types are exactly the events.py event types, with an optional
per-rule filter in `trigger_config` (currently: `folder_id` for
folder_file_added). Action types:

  "prompt"  — send a message into a persistent conversation (created on
              first fire, reused after — same pattern as schedule_service),
              chat or research mode only. Deliberately never agent mode:
              an unattended, unsupervised trigger running shell commands
              is the same escalation schedule_service already refuses,
              for the same reason (see its docstring / README's Safety
              model).
  "webhook" — POST the event payload to one specific URL, for a rule
              that wants a bespoke receiver instead of the global list
              in Settings -> Automation.

`{event_data}` in a prompt template is substituted with a compact
JSON rendering of the triggering event's data, so the prompt can
reference what actually happened.
"""
from __future__ import annotations

import json

from app.core.logging import get_logger
from app.db import storage

log = get_logger(__name__)


def _matches_filter(rule: dict, data: dict) -> bool:
    cfg = rule.get("trigger_config") or {}
    if rule["trigger_type"] == "folder_file_added" and cfg.get("folder_id"):
        return cfg["folder_id"] == data.get("folder_id")
    return True


async def _run_prompt_action(rule: dict, data: dict) -> None:
    from app.db import storage as _storage
    from app.services.orchestrator import run_turn

    cfg = rule.get("action_config") or {}
    prompt = str(cfg.get("prompt", "")).strip()
    if not prompt:
        return
    prompt = prompt.replace("{event_data}", json.dumps(data)[:2000])

    conversation_id = rule.get("conversation_id")
    if not conversation_id:
        conv = _storage.create_conversation(f"[Automation] {rule['name']}", cfg.get("project_id"))
        conversation_id = conv["id"]
        storage.set_automation_rule_conversation(rule["id"], conversation_id)

    if cfg.get("mode") == "research":
        from app.services import research_service
        async for ev in research_service.run_deep_research(conversation_id, prompt, []):
            pass  # persists its own messages; nothing else to do with the events here
        return

    decision, stream, _sources, assistant_parent_id = await run_turn(conversation_id, prompt, [])
    collected = [piece async for piece in stream]
    full_text = "".join(collected)
    if full_text.strip():
        _storage.add_message(
            conversation_id, "assistant", full_text,
            model=decision.model, route_role=decision.role, route_reason=decision.reason,
            parent_id=assistant_parent_id,
        )


async def _run_webhook_action(rule: dict, data: dict) -> None:
    import time
    import httpx

    cfg = rule.get("action_config") or {}
    url = cfg.get("url")
    if not url:
        return
    payload = {"event": rule["trigger_type"], "timestamp": time.time(), "data": data, "rule": rule["name"]}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            await client.post(url, json=payload)
    except Exception as exc:
        log.warning("automation.webhook_action_failed", rule_id=rule["id"], error=str(exc))


async def handle_event(event_type: str, data: dict) -> None:
    rules = [r for r in storage.list_automation_rules(enabled_only=True) if r["trigger_type"] == event_type]
    for rule in rules:
        if not _matches_filter(rule, data):
            continue
        try:
            if rule["action_type"] == "prompt":
                await _run_prompt_action(rule, data)
            elif rule["action_type"] == "webhook":
                await _run_webhook_action(rule, data)
            storage.mark_automation_rule_fired(rule["id"])
            log.info("automation.rule_fired", rule_id=rule["id"], name=rule["name"], event=event_type)
        except Exception as exc:
            log.warning("automation.rule_failed", rule_id=rule["id"], error=str(exc))
