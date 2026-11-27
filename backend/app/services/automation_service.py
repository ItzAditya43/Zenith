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
import re

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
        async for _ev in research_service.run_deep_research(conversation_id, prompt, []):
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
    from app.services import webhook_service

    cfg = rule.get("action_config") or {}
    url = cfg.get("url")
    if not url:
        return
    try:
        await webhook_service.deliver(url, rule["trigger_type"], data, extra={"rule": rule["name"]})
    except Exception as exc:  # noqa: BLE001
        log.warning("automation.webhook_action_failed", rule_id=rule["id"], error=str(exc))


def _fill(template: str, data: dict) -> str:
    """{field} placeholders from the event's data; unknown ones stay as-is."""
    def sub(m):
        v = data.get(m.group(1))
        return str(v) if v not in (None, "") else m.group(0)
    return re.sub(r"\{([a-zA-Z_]+)\}", sub, template)


async def add_todo_once(text: str, due_ts: float | None = None, source: str = "", via_rule: str | None = None) -> dict | None:
    """Create a to-do unless an open one with the same text exists, and
    announce it (todo_created) so other rules can react. Returns the new
    to-do, or None if it was a duplicate."""
    text = " ".join(text.split())[:500]
    if not text:
        return None
    if any(not t.get("done") and t["text"].strip().lower() == text.lower() for t in storage.list_todos()):
        return None
    todo = storage.create_todo(text, due_ts)
    from app.services import events
    await events.emit("todo_created", {"id": todo["id"], "text": text, "source": source, "via_rule": via_rule})
    return todo


async def _run_todo_action(rule: dict, data: dict) -> None:
    import time as _time

    cfg = rule.get("action_config") or {}
    text = _fill(str(cfg.get("text") or "").strip(), data)
    hours = cfg.get("due_in_hours")
    due = _time.time() + float(hours) * 3600 if hours not in (None, "") else None
    await add_todo_once(text, due, source=f"rule:{rule['name']}", via_rule=rule["id"])


async def handle_event(event_type: str, data: dict) -> None:
    rules = [r for r in storage.list_automation_rules(enabled_only=True) if r["trigger_type"] == event_type]
    for rule in rules:
        if not _matches_filter(rule, data):
            continue
        if data.get("via_rule") == rule["id"]:
            continue  # a rule never re-fires on its own output (no loops)
        try:
            if rule["action_type"] == "prompt":
                await _run_prompt_action(rule, data)
            elif rule["action_type"] == "webhook":
                await _run_webhook_action(rule, data)
            elif rule["action_type"] == "todo":
                await _run_todo_action(rule, data)
            storage.mark_automation_rule_fired(rule["id"])
            log.info("automation.rule_fired", rule_id=rule["id"], name=rule["name"], event=event_type)
        except Exception as exc:
            log.warning("automation.rule_failed", rule_id=rule["id"], error=str(exc))


SAMPLE_EVENTS: dict[str, dict] = {
    "digest_generated": {"digest_id": "sample", "files_changed": 3, "memories_added": 1},
    "schedule_completed": {"schedule_id": "sample", "name": "Morning brief", "summary": "Three things changed overnight."},
    "schedule_failing": {"schedule_id": "sample", "name": "Morning brief", "failures": 3, "paused": False},
    "urgent_email": {"from": "boss@example.com", "subject": "Need this today", "summary": "Asks for the report by 5pm."},
    "memory_conflict_found": {"memory_a": "uses fish shell", "memory_b": "uses zsh"},
    "folder_file_added": {"folder_id": "sample", "path": "/notes/new-idea.md"},
    "agent_run_finished": {"id": "sample", "prompt": "Fix the failing test", "summary": "Edited 2 files."},
    "agent_run_needs_approval": {"id": "sample", "prompt": "Clean up", "detail": "wants to run rm -rf build/"},
    "todo_created": {"id": "sample", "text": "Call the plumber", "source": "manual"},
    "todo_completed": {"id": "sample", "text": "Call the plumber"},
}


def dry_run(rule: dict, data: dict | None = None) -> dict:
    """What this rule would do for one event — nothing is run, sent or saved."""
    event = rule["trigger_type"]
    data = data if data is not None else SAMPLE_EVENTS.get(event, {})
    cfg = rule.get("action_config") or {}
    out: dict = {"trigger": event, "event_data": data, "matches_filter": _matches_filter(rule, data),
                 "action": rule["action_type"]}
    if rule["action_type"] == "prompt":
        prompt = str(cfg.get("prompt", "")).replace("{event_data}", json.dumps(data)[:2000])
        conv = rule.get("conversation_id")
        out.update(prompt=prompt, mode=cfg.get("mode") or "chat",
                   target=f"conversation {conv}" if conv else f'a new conversation "[Automation] {rule.get("name", "")}"',
                   expected="A chat or research reply posted in that conversation. It can't run tools or commands.")
    elif rule["action_type"] == "webhook":
        payload = {"event": event, "delivery_id": "<generated>", "schema_version": 1, "data": data, "rule": rule.get("name")}
        out.update(target=cfg.get("url"), payload=payload,
                   expected="One signed POST, retried up to 3 times on network errors or 5xx.")
        try:
            from app.services.webhook_service import check_target
            check_target(str(cfg.get("url") or ""))
        except Exception as exc:  # noqa: BLE001
            out["problem"] = str(exc)
    elif rule["action_type"] == "todo":
        out.update(text=_fill(str(cfg.get("text") or ""), data), due_in_hours=cfg.get("due_in_hours"),
                   expected="Adds the to-do unless an open one with the same text already exists.")
    return out
