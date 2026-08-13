"""Router self-tuning surface.

  GET /api/routing/override-summary — how often the user has manually
  overridden the auto-router's model pick per role, grouped and counted.
  This is the read side of `storage.log_routing_override` (written from
  `orchestrator.run_turn` whenever a per-message `model_override` actually
  differs from what the router would have auto-picked). Pure local
  frequency-counting, no ML — the UI uses this to suggest pinning a role
  to the model the user keeps switching to (Settings -> Model routing
  already has the pin mechanism via PATCH /api/config's `model_overrides`;
  this only surfaces the signal, it doesn't add a new way to pin).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.db import storage

router = APIRouter(prefix="/api/routing", tags=["routing"])


@router.get("/override-summary")
async def override_summary(days: int = 30):
    return {"days": days, "overrides": storage.routing_override_summary(days=days)}
