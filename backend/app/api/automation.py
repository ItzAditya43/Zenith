"""Outbound webhooks + automation rules — see events.py, webhook_service.py,
automation_service.py.

  GET    /api/webhooks               list
  POST   /api/webhooks               create
  PATCH  /api/webhooks/{id}          enable/disable
  DELETE /api/webhooks/{id}          delete
  GET    /api/automation/event-types available trigger/event types
  GET    /api/automation/rules       list
  POST   /api/automation/rules       create
  PATCH  /api/automation/rules/{id}  enable/disable
  DELETE /api/automation/rules/{id}  delete
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import storage
from app.models.schemas import AutomationRuleCreate, WebhookCreate

router = APIRouter(prefix="/api", tags=["automation"])


@router.get("/automation/event-types")
async def event_types():
    from app.services.events import EVENT_TYPES
    return EVENT_TYPES


@router.get("/webhooks")
async def list_webhooks():
    return storage.list_webhooks()


@router.post("/webhooks")
async def create_webhook(body: WebhookCreate):
    from app.services.events import EVENT_TYPES
    bad = [e for e in body.event_types if e not in EVENT_TYPES]
    if bad:
        raise HTTPException(422, f"Unknown event type(s): {bad}")
    return storage.create_webhook(body.url, body.event_types)


@router.patch("/webhooks/{webhook_id}")
async def toggle_webhook(webhook_id: str, body: dict):
    storage.set_webhook_enabled(webhook_id, bool(body.get("enabled")))
    return {"ok": True}


@router.delete("/webhooks/{webhook_id}")
async def remove_webhook(webhook_id: str):
    storage.delete_webhook(webhook_id)
    return {"ok": True}


@router.get("/automation/rules")
async def list_rules():
    return storage.list_automation_rules()


@router.post("/automation/rules")
async def create_rule(body: AutomationRuleCreate):
    from app.services.events import EVENT_TYPES
    if body.trigger_type not in EVENT_TYPES:
        raise HTTPException(422, f"trigger_type must be one of {EVENT_TYPES}")
    if body.action_type not in ("prompt", "webhook"):
        raise HTTPException(422, "action_type must be 'prompt' or 'webhook'")
    if body.action_type == "prompt" and not body.action_config.get("prompt"):
        raise HTTPException(422, "action_config.prompt is required for a prompt action.")
    if body.action_type == "webhook" and not body.action_config.get("url"):
        raise HTTPException(422, "action_config.url is required for a webhook action.")
    return storage.create_automation_rule(
        body.name, body.trigger_type, body.trigger_config, body.action_type, body.action_config,
    )


@router.patch("/automation/rules/{rule_id}")
async def toggle_rule(rule_id: str, body: dict):
    storage.set_automation_rule_enabled(rule_id, bool(body.get("enabled")))
    return {"ok": True}


@router.delete("/automation/rules/{rule_id}")
async def remove_rule(rule_id: str):
    storage.delete_automation_rule(rule_id)
    return {"ok": True}
