from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schemas import ConfigPatch
from app.services.ollama_client import OllamaClient, OllamaError
from app.services.router import ModelRouter

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/models")
async def models():
    """Lists installed Ollama models along with which capability role(s)
    the router currently thinks each one satisfies — this is what powers
    the 'auto-detected roles' view in Settings."""
    client = OllamaClient()
    try:
        raw = await client.list_models()
    except OllamaError as exc:
        raise HTTPException(503, str(exc))

    keywords = settings.get("capability_keywords", {})
    overrides = settings.get("model_overrides", {})
    enriched = []
    for m in raw:
        name = m["name"]
        lname = name.lower()
        roles = [role for role, kws in keywords.items() if any(kw in lname for kw in kws)]
        roles += [role for role, override in overrides.items() if override == name and role not in roles]
        enriched.append({**m, "roles": roles})
    return enriched


@router.get("/config")
async def get_config():
    cfg = dict(settings.all())
    return cfg


@router.patch("/config")
async def patch_config(body: ConfigPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return settings.update(patch)


@router.post("/route/preview")
async def preview_route(text: str = "", has_image: bool = False, has_video: bool = False):
    """Lets the Settings UI show 'this message would go to <model>' live,
    without actually sending anything to Ollama."""
    router_ = ModelRouter()
    try:
        decision = await router_.decide(text=text, has_image=has_image, has_video=has_video)
    except OllamaError as exc:
        raise HTTPException(503, str(exc))
    return {"model": decision.model, "role": decision.role, "reason": decision.reason}
