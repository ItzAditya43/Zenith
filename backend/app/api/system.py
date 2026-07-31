"""
System / configuration endpoints.

  GET  /api/health         — probes Ollama + (lazily) Whisper/TTS, returns ok/degraded/down
  GET  /api/models         — list installed Ollama models + auto-classified roles
  GET  /api/models/refresh — bust the ModelRegistry TTL cache
  GET  /api/config         — full settings dump
  PATCH /api/config        — partial update with field-level validation
  POST /api/route/preview  — dry-run the router on a sample input
"""
from __future__ import annotations

import asyncio
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import ConfigPatch
from app.services.ollama_client import OllamaClient, OllamaError
from app.services.router import ModelRegistry, ModelRouter

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["system"])

# Phase 7 #5 — low-churn endpoints get a short Cache-Control so the browser
# doesn't re-fetch on every navigation. Busted on config/model change via the
# existing 15s TTL cache + /api/models/refresh.
_CACHE_MAX_AGE = int(settings.get("static_cache_seconds", 15))


async def _ollama_status(client: OllamaClient) -> dict:
    """Probe Ollama. Returns a small dict so the caller can compose the
    overall health response without re-doing the work."""
    t0 = time.time()
    try:
        models = await asyncio.wait_for(client.list_models(), timeout=2.5)
        return {
            "ok": True,
            "models": len(models),
            "latency_ms": int((time.time() - t0) * 1000),
        }
    except Exception as exc:  # OllamaError, asyncio.TimeoutError, etc.
        return {
            "ok": False,
            "error": str(exc)[:200],
            "latency_ms": int((time.time() - t0) * 1000),
        }


async def _whisper_status() -> dict:
    """Whisper is loaded lazily on first STT call. A successful import + a
    cached model file is a strong enough 'available' signal without paying
    the multi-second load cost on every /api/health poll."""
    try:
        from faster_whisper import WhisperModel  # noqa: F401

        return {"ok": True, "lazy": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


async def _tts_status() -> dict:
    """TTS is also lazy. We just check that the configured piper voice
    file exists (or the fallback directory contains at least one .onnx)."""
    try:
        from pathlib import Path

        from app.services.tts_service import _piper_voice_paths

        paths = _piper_voice_paths()
        if paths and Path(paths[0]).exists():
            return {"ok": True, "voice": settings.get("piper_voice")}
        return {"ok": False, "error": "no piper voice installed"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def _overall(ollama: dict, whisper: dict, tts: dict) -> Literal["ok", "degraded", "down"]:
    """Ollama is required; Whisper/TTS being unavailable only downgrades
    the app (text chat still works), so it doesn't push us from `degraded`
    to `down` on its own."""
    if not ollama.get("ok"):
        return "down"
    if not whisper.get("ok") or not tts.get("ok"):
        return "degraded"
    return "ok"


@router.get("/health")
async def health():
    """Probes the real dependencies instead of returning a static `ok`.

    The shape is deliberately forward-compatible: `components` lists each
    dependency and its own status so a UI/monitoring layer can render a
    richer health view later without an API change."""
    ollama, whisper, tts = await asyncio.gather(
        _ollama_status(OllamaClient()),
        _whisper_status(),
        _tts_status(),
    )
    status = _overall(ollama, whisper, tts)
    log.info("health.probe", status=status, ollama=ollama.get("ok"), whisper=whisper.get("ok"), tts=tts.get("ok"))
    payload = {
        "status": status,
        "components": {
            "ollama": ollama,
            "whisper": whisper,
            "tts": tts,
        },
    }
    if status == "down":
        # Use 503 so monitoring / load balancers can act on it.
        raise HTTPException(status_code=503, detail=payload)
    return payload


@router.get("/activity")
async def activity():
    """What's actually running right now, across the whole backend (not
    scoped to one conversation) — powers the header's live status rail.
    Cheap in-memory reads, no I/O, safe to poll frequently."""
    from app.services import agent_service, browser_service, schedule_service

    shell_sessions = [
        {"id": s["id"], "command": s["command"], "alive": s["alive"], "conversation_id": s["conversation_id"]}
        for s in agent_service._shell_sessions.values()
    ]
    browser_sessions = [
        {"conversation_id": cid, "url": s["url"]}
        for cid, s in browser_service._browser_sessions.items()
    ]
    due_schedules = []
    try:
        due_schedules = [
            {"id": s["id"], "name": s["name"]}
            for s in schedule_service.list_schedules()
            if s.get("enabled") and s.get("next_run_at") and s["next_run_at"] <= time.time() + 60
        ]
    except Exception:
        pass
    return {
        "shell_sessions": shell_sessions,
        "browser_sessions": browser_sessions,
        "due_schedules": due_schedules,
        "count": len(shell_sessions) + len(browser_sessions),
    }


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
    return JSONResponse(enriched, headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"})


@router.post("/models/refresh")
async def models_refresh():
    """Force the ModelRegistry's TTL cache to bust. Useful after the
    user runs `ollama pull <something>` from outside the app."""
    registry = ModelRegistry()
    await registry.models(force=True)
    return {"ok": True, "models": await registry.models()}


def _model_progress_sse(gen):
    """Wrap an Ollama pull/create progress stream as SSE, busting the model
    cache when it completes so the new model shows up immediately."""
    import json as _json

    async def stream():
        client = OllamaClient()
        try:
            async for ev in gen(client):
                yield f"data: {_json.dumps(ev)}\n\n"
            await ModelRegistry().models(force=True)
            yield f"data: {_json.dumps({'status': 'done'})}\n\n"
        except OllamaError as exc:
            yield f"data: {_json.dumps({'error': str(exc)})}\n\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/models/pull")
async def models_pull(body: dict):
    """Stream `ollama pull <name>` progress as SSE."""
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "A model name is required.")
    return _model_progress_sse(lambda c: c.pull_model(name))


@router.post("/models/create")
async def models_create(body: dict):
    """Create a model variant from a base model (`from`), optionally applying
    a system prompt or a LoRA/fine-tune adapter (`adapter` = path to a GGUF
    adapter). Streams progress as SSE."""
    name = str(body.get("name", "")).strip()
    base = str(body.get("from", "")).strip()
    if not name or not base:
        raise HTTPException(400, "A new model name and a base model ('from') are required.")
    spec = {
        "from": base,
        "system": str(body.get("system", "")).strip(),
        "adapter": str(body.get("adapter", "")).strip(),
    }
    return _model_progress_sse(lambda c: c.create_model(name, spec))


@router.delete("/models/{name:path}")
async def models_delete(name: str):
    """Delete an installed model. `:path` so tags with slashes work."""
    client = OllamaClient()
    try:
        await client.delete_model(name)
    except OllamaError as exc:
        raise HTTPException(503, str(exc))
    await ModelRegistry().models(force=True)
    return {"ok": True}


@router.get("/models/{name:path}/show")
async def models_show(name: str):
    """Model details (parameters, template, license) from `ollama show`."""
    client = OllamaClient()
    try:
        return await client.show_model(name)
    except OllamaError as exc:
        raise HTTPException(503, str(exc))


@router.get("/config")
async def get_config():
    return JSONResponse(dict(settings.all()), headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"})


@router.patch("/config")
async def patch_config(body: ConfigPatch):
    """Apply a partial config update. `ConfigPatch` (Pydantic) rejects
    unknown fields and validates enums/ranges, so we get a 422 instead of
    silently writing garbage into config.json."""
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = settings.update(patch)
    # Bust the model registry so role/override changes take effect on the
    # next /api/chat request instead of waiting for the TTL.
    try:
        await ModelRegistry().models(force=True)
    except Exception:  # never let a cache-bust failure block a config save
        pass
    return updated


@router.post("/route/preview")
async def preview_route(text: str = "", has_image: bool = False, has_video: bool = False, request: Request = None):
    """Lets the Settings UI show 'this message would go to <model>' live,
    without actually sending anything to Ollama."""
    router_ = ModelRouter()
    try:
        decision = await router_.decide(
            text=text,
            has_image=has_image,
            has_video=has_video,
            history_last_model=(getattr(request.app.state, "last_route_model", None) if request else None),
        )
    except OllamaError as exc:
        raise HTTPException(503, str(exc))
    return {
        "model": decision.model,
        "role": decision.role,
        "reason": decision.reason,
        "confidence": decision.confidence,
    }

@router.get("/skills")
async def list_skills():
    """Auto-detected + manually-saved reusable agent playbooks. See
    storage.record_skill_run for the detection heuristic."""
    from app.db import storage
    return storage.list_skills()


@router.post("/skills")
async def create_skill(body: dict):
    from app.db import storage
    name = str(body.get("name", "")).strip()
    prompt_template = str(body.get("prompt_template", "")).strip()
    if not name or not prompt_template:
        raise HTTPException(422, "name and prompt_template are required.")
    return storage.save_skill_manual(name, prompt_template, str(body.get("description", "")))


@router.delete("/skills/{skill_id}")
async def remove_skill(skill_id: str):
    from app.db import storage
    storage.delete_skill(skill_id)
    return {"ok": True}


@router.get("/hardware")
async def hardware_report():
    """Detected CPU/RAM/GPU + a fit rating for installed models and a
    small cookbook of recommended models sized to what this machine can
    actually run. Heuristic, not a guarantee — see hardware_service."""
    from app.services import hardware_service
    from app.services.router import ModelRegistry

    registry = ModelRegistry()
    installed = await registry.models()
    return hardware_service.score_models(installed)
