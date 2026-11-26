"""API model providers (see app/services/providers.py).

  GET    /api/providers               configured providers (keys never returned)
  GET    /api/providers/presets       ready-made entries for the add form
  POST   /api/providers               create or update {id, name, kind, base_url, api_key?, models?, enabled?}
  DELETE /api/providers/{id}
  POST   /api/providers/{id}/test     list its models: proves the URL and key work
  POST   /api/providers/check         guided check: address, reach, key, models, a real reply (+tools, embeddings)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import Field

from app.models.schemas import StrictModel
from app.services import providers

router = APIRouter(prefix="/api/providers", tags=["providers"])


class ProviderBody(StrictModel):
    id: str = Field(min_length=1, max_length=32)
    name: str = Field(default="", max_length=60)
    kind: str = Field(default="openai", pattern="^(openai|anthropic)$")
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    clear_key: bool = False
    models: list[str] = Field(default_factory=list, max_length=200)
    enabled: bool = True
    roles: list[str] = Field(default_factory=list, max_length=10)
    price_in: float | None = Field(default=None, ge=0)
    price_out: float | None = Field(default=None, ge=0)
    monthly_limit: float | None = Field(default=None, ge=0)


@router.get("")
async def list_providers():
    return {"providers": providers.list_public()}


@router.get("/usage")
async def provider_usage():
    """This month's calls, tokens and estimated cost per provider."""
    from app.services import spend_service

    return {"usage": [spend_service.month_summary(p) for p in providers._all()]}  # noqa: SLF001


@router.get("/presets")
async def presets():
    return {"presets": providers.PRESETS}


@router.post("")
async def save_provider(body: ProviderBody):
    try:
        saved = providers.save(body.model_dump())
    except providers.ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    await _bust_registry()
    return saved


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str):
    if not providers.delete(provider_id):
        raise HTTPException(404, "No such provider.")
    await _bust_registry()
    return {"deleted": provider_id}


class CheckBody(StrictModel):
    id: str | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, max_length=60)
    kind: str = "openai"
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    thorough: bool = False


@router.post("/check")
async def check_provider(body: CheckBody):
    """Guided connection check for a saved provider ({id}) or one being set
    up (base_url + api_key). Never echoes the key."""
    from app.services import provider_check

    entry = body.model_dump(exclude={"model", "thorough"})
    return await provider_check.check(entry, body.model, body.thorough)


@router.post("/{provider_id}/test")
async def test_provider(provider_id: str):
    p = providers.get(provider_id)
    if not p:
        raise HTTPException(404, "No such provider.")
    try:
        models = await providers.models_of(p, force=True)
    except providers.ProviderError as exc:
        return {"ok": False, "error": str(exc), "models": []}
    return {"ok": True, "error": None, "models": models[:500], "count": len(models)}


async def _bust_registry() -> None:
    try:
        from app.services.router import ModelRegistry
        await ModelRegistry().models(force=True)
    except Exception:
        pass
