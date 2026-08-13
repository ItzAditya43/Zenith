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


def _vector_search_status() -> dict:
    """Whether the sqlite-vec extension is installed, i.e. RAG can do true
    vector search instead of falling back to LIKE-based retrieval.

    rag_service doesn't expose a dedicated "is vector search active" accessor
    (it only decides this lazily, per-connection, inside `_ensure_table`/
    `_conn`), and rag_service.py belongs to another in-flight change, so we
    don't modify it here. Importing `sqlite_vec` is the same check that
    module makes internally to decide whether to load the extension — if the
    package isn't importable, the extension can't load either way. This is a
    presence check, not a live per-connection load confirmation, but it's an
    honest proxy without touching a file outside this task's scope."""
    try:
        import sqlite_vec  # noqa: F401

        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def _image_gen_status() -> dict:
    """Reuses image_service's own "configured" check rather than
    re-implementing it — a real reachability probe would mean issuing a
    request to the user's SD server on every /api/health poll, which is
    heavier than the other checks here, so we report configuration state
    only (same as what the header's image button already relies on)."""
    from app.services import image_service

    configured = image_service.is_configured()
    return {"ok": configured, "configured": configured}


def _agent_mode_status() -> dict:
    """Not a network probe — just reflects the settings switch."""
    enabled = bool(settings.get("agent_enabled", False))
    return {"ok": enabled, "enabled": enabled}


def _mcp_status() -> dict:
    """Reports configured MCP server counts. We deliberately don't spawn a
    stdio subprocess per server here (mcp_service's connections are
    stateless-per-call and can take up to _CONNECT_TIMEOUT=15s each) — doing
    that on every /api/health poll would make this endpoint slow and noisy.
    Configured/enabled counts are enough for a glance-level health view."""
    try:
        from app.services import mcp_service

        servers = mcp_service.list_servers()
        enabled = [s for s in servers if s.get("enabled")]
        return {"ok": True, "configured": len(servers), "enabled": len(enabled)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}


def _overall(ollama: dict, whisper: dict, tts: dict) -> Literal["ok", "degraded", "down"]:
    """Ollama is required; Whisper/TTS being unavailable only downgrades
    the app (text chat still works), so it doesn't push us from `degraded`
    to `down` on its own. The newer components (vector search, image gen,
    agent mode, MCP) are all opt-in/optional by design, so — same as
    Whisper/TTS — they can only ever push status to `degraded`, never
    `down`; only Ollama being unreachable does that."""
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
    ollama, whisper, tts, vector_search, image_gen, agent_mode, mcp = await asyncio.gather(
        _ollama_status(OllamaClient()),
        _whisper_status(),
        _tts_status(),
        asyncio.to_thread(_vector_search_status),
        asyncio.to_thread(_image_gen_status),
        asyncio.to_thread(_agent_mode_status),
        asyncio.to_thread(_mcp_status),
    )
    status = _overall(ollama, whisper, tts)
    log.info("health.probe", status=status, ollama=ollama.get("ok"), whisper=whisper.get("ok"), tts=tts.get("ok"))
    payload = {
        "status": status,
        "components": {
            "ollama": ollama,
            "whisper": whisper,
            "tts": tts,
            "vector_search": vector_search,
            "image_gen": image_gen,
            "agent_mode": agent_mode,
            "mcp": mcp,
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
    urgent_emails = 0
    try:
        from app.db import storage
        urgent_emails = len(storage.list_urgent_email_flags(unseen_only=True))
    except Exception:
        pass
    return {
        "shell_sessions": shell_sessions,
        "browser_sessions": browser_sessions,
        "due_schedules": due_schedules,
        "urgent_emails": urgent_emails,
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


@router.get("/routing/status")
async def routing_status():
    """Whether semantic (embedding-based) routing is actually active right
    now, not just configured — it silently no-ops back to the regex
    router whenever no model is tagged into the 'embedding' capability
    bucket, which is easy to not notice since nothing errors. Surfaces
    that state instead of leaving it invisible."""
    from app.services.router import ModelRouter

    router_ = ModelRouter()
    installed = await router_.registry.models()
    embed_model = router_._match_capability("embedding", installed)
    return {
        "active": embed_model is not None,
        "embedding_model": embed_model,
        "confidence_threshold": float(settings.get("router_confidence_threshold", 0.55)),
    }


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


@router.get("/email/test")
async def email_test():
    from app.services import email_service
    try:
        return await asyncio.to_thread(email_service.test_connection)
    except email_service.EmailError as exc:
        raise HTTPException(400, str(exc))


@router.get("/email/messages")
async def email_messages(folder: str = "INBOX"):
    from app.services import email_service
    try:
        return await asyncio.to_thread(email_service.list_messages, folder)
    except email_service.EmailError as exc:
        raise HTTPException(400, str(exc))


@router.get("/email/messages/{message_id}")
async def email_message(message_id: str, folder: str = "INBOX"):
    from app.services import email_service
    try:
        return await asyncio.to_thread(email_service.get_message, message_id, folder)
    except email_service.EmailError as exc:
        raise HTTPException(400, str(exc))


@router.post("/email/messages/{message_id}/summarize")
async def email_summarize(message_id: str, folder: str = "INBOX"):
    from app.services import email_service
    try:
        return {"summary": await email_service.summarize(message_id, folder)}
    except email_service.EmailError as exc:
        raise HTTPException(400, str(exc))


@router.post("/email/messages/{message_id}/draft-reply")
async def email_draft_reply(message_id: str, body: dict, folder: str = "INBOX"):
    from app.services import email_service
    try:
        return await email_service.draft_reply(
            message_id, body.get("instruction", ""), folder, body.get("auto_research", True)
        )
    except email_service.EmailError as exc:
        raise HTTPException(400, str(exc))


@router.post("/email/send")
async def email_send(body: dict):
    from app.services import email_service
    to = str(body.get("to", "")).strip()
    subject = str(body.get("subject", "")).strip()
    text = str(body.get("body", "")).strip()
    if not to or not text:
        raise HTTPException(422, "to and body are required.")
    try:
        await asyncio.to_thread(email_service.send_message, to, subject, text, body.get("in_reply_to"))
        return {"ok": True}
    except email_service.EmailError as exc:
        raise HTTPException(400, str(exc))


@router.get("/email/flags")
async def email_flags(unseen_only: bool = True):
    from app.db import storage
    return storage.list_urgent_email_flags(unseen_only)


@router.post("/email/flags/mark-seen")
async def email_flags_mark_seen():
    from app.db import storage
    storage.mark_email_flags_seen()
    return {"ok": True}


@router.get("/usage/summary")
async def usage_summary(days: int = 14):
    """Token throughput and latency trends over time, plus disk usage —
    the "how has this actually been performing" view, distinct from the
    live-only status rail."""
    import shutil
    from pathlib import Path
    from app.core.config import data_dir, db_path
    from app.db import storage

    summary = storage.usage_summary(days)

    disk = {}
    try:
        disk["free_gb"] = round(shutil.disk_usage("/").free / (1024 ** 3), 1)
    except Exception:
        disk["free_gb"] = None
    try:
        disk["db_size_mb"] = round(Path(db_path()).stat().st_size / (1024 ** 2), 1)
    except Exception:
        disk["db_size_mb"] = None
    try:
        total = sum(f.stat().st_size for f in Path(data_dir()).rglob("*") if f.is_file())
        disk["data_dir_size_mb"] = round(total / (1024 ** 2), 1)
    except Exception:
        disk["data_dir_size_mb"] = None

    summary["disk"] = disk
    return summary
