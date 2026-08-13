from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agent, automation, chat, digest, documents, export, files, folders, graph, images, lock, mcp, memory, routing, schedules, sync, system, upload, voice
from app.core.config import settings
from app.core.logging import get_logger
from app.db.storage import init_db
from app.services.attachments import sweep_orphans
from app.services.ollama_client import OllamaClient

log = get_logger(__name__)


async def _orphan_sweeper(interval_seconds: int) -> None:
    """Periodically purge attachments not bound to any conversation.

    Runs forever in the background; cancellation is handled by FastAPI's
    shutdown (the surrounding `asyncio.create_task` is cancelled at exit)."""
    try:
        while True:
            try:
                removed = await asyncio.to_thread(sweep_orphans)
                if removed:
                    log.info("upload.sweeper_tick", removed=removed)
            except Exception as exc:  # never let the sweeper die silently
                log.warning("upload.sweeper_error", error=str(exc))
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("upload.sweeper_stopped")
        raise


async def _folder_scanner(interval_seconds: int) -> None:
    """Periodically re-scans all enabled watched folders. Same
    fire-and-forget pattern as the orphan sweeper — a single bad folder
    (deleted, permission error) is logged and skipped, never crashes
    the loop."""
    from app.services.folder_service import scan_all_enabled

    try:
        while True:
            try:
                await scan_all_enabled()
            except Exception as exc:
                log.warning("folder.scanner_error", error=str(exc))
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("folder.scanner_stopped")
        raise


async def _schedule_runner(interval_seconds: int) -> None:
    """Checks for due schedules and runs them. Same fire-and-forget
    pattern as the orphan sweeper / folder scanner — one schedule
    erroring never stops the loop; schedule_service.run_due_schedules
    already isolates per-schedule failures into their run records."""
    from app.services.schedule_service import run_due_schedules

    try:
        while True:
            try:
                await run_due_schedules()
            except Exception as exc:
                log.warning("schedule.runner_error", error=str(exc))
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("schedule.runner_stopped")
        raise


async def _digest_runner(interval_seconds: int) -> None:
    """Checks whether an ambient daily digest is due and generates one if
    so. Off entirely unless `digest_enabled` — digest_service.maybe_run_digest
    checks that itself, same no-op-when-off pattern as the other loops."""
    from app.services.digest_service import maybe_run_digest

    try:
        while True:
            try:
                await maybe_run_digest()
            except Exception as exc:
                log.warning("digest.runner_error", error=str(exc))
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("digest.runner_stopped")
        raise


async def _email_triage_runner(interval_seconds: int) -> None:
    """Background inbox scan: flags urgent messages so you don't have to
    keep the inbox open to catch a signature deadline. Same fire-and-forget
    pattern as the other background loops — off entirely unless email is
    configured (scan_for_urgent no-ops immediately in that case)."""
    from app.services.email_service import scan_for_urgent

    try:
        while True:
            try:
                await scan_for_urgent()
            except Exception as exc:
                log.warning("email.triage_runner_error", error=str(exc))
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        log.info("email.triage_runner_stopped")
        raise


async def _prewarm() -> None:
    """Load the general-role model into Ollama's memory so the first turn
    doesn't pay the multi-second cold-load cost. Best-effort, off the
    startup critical path (runs as a background task)."""
    try:
        from app.services.router import ModelRegistry, ModelRouter

        registry = ModelRegistry()
        installed = await registry.models()
        cfg = settings.get("fallback_model", "general")
        # `fallback_model` is either an exact installed name or a role.
        if cfg in installed:
            model = cfg
        else:
            model = ModelRouter(registry=registry)._match_capability(  # noqa: SLF001
                cfg or "general", installed
            )
        if not model:
            log.info("prewarm.skipped", reason="no matching model installed")
            return
        await OllamaClient().preload(model)
        log.info("prewarm.done", model=model)
    except Exception as exc:
        log.warning("prewarm.failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    interval = int(settings.get("upload_sweep_interval_seconds", 30 * 60))
    sweeper = asyncio.create_task(_orphan_sweeper(interval))
    folder_interval = int(settings.get("folder_scan_interval_seconds", 600))
    folder_scanner = asyncio.create_task(_folder_scanner(folder_interval))
    schedule_interval = int(settings.get("schedule_check_interval_seconds", 60))
    schedule_runner = asyncio.create_task(_schedule_runner(schedule_interval))
    email_triage_runner = asyncio.create_task(_email_triage_runner(300))
    digest_interval = int(settings.get("digest_check_interval_seconds", 3600))
    digest_runner = asyncio.create_task(_digest_runner(digest_interval))
    # Track the last model used in this process so the router can be
    # "sticky" — see ModelRouter.decide() and the /api/route/preview docstring.
    app.state.last_route_model = None
    # Phase 7 #4 — optionally pre-load the configured general model on
    # startup to cut first-turn latency. Off by default on low-VRAM setups.
    if bool(settings.get("prewarm_model_on_startup", False)):
        asyncio.create_task(_prewarm())
    try:
        yield
    finally:
        sweeper.cancel()
        folder_scanner.cancel()
        schedule_runner.cancel()
        email_triage_runner.cancel()
        digest_runner.cancel()
        for task in (sweeper, folder_scanner, schedule_runner, email_triage_runner, digest_runner):
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Zenith",
    version="0.1.0",
    lifespan=lifespan,
    description="Local-first AI chat with a small router over local Ollama models.",
)


def _cors_origins() -> list[str]:
    """Resolve the CORS allowlist from settings, falling back to safe
    localhost defaults. The previous hard-coded `*` is gone: tighten
    the list in the Settings panel (cors_allow_origins) if you expose
    the backend beyond localhost."""
    origins = settings.get("cors_allow_origins")
    if not origins:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            # The desktop app's webview — Tauri v2 serves the frontend from
            # its own custom scheme, not localhost, so without these the
            # bundled backend silently CORS-blocks every request from the
            # installed app (config/models/schedules all "fail to load").
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    return list(origins)


# Opt-in LAN/Tailscale origin matching for multi-device access. Matches
# http(s)://{localhost|private-IP|*.ts.net}[:port] — private ranges are
# 10/8, 192.168/16, 172.16-31/12. Off unless cors_allow_lan is set.
_LAN_ORIGIN_REGEX = (
    r"^https?://("
    r"localhost|127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
    r"[a-zA-Z0-9-]+\.ts\.net"
    r")(:\d+)?$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=_LAN_ORIGIN_REGEX if bool(settings.get("cors_allow_lan", False)) else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Optional shared-secret auth (Tier 1 #8) ---
# Off by default. When enabled, callers must send
#   Authorization: Bearer <auth_shared_secret>
# on every /api/* request, or  X-Zenith-Secret: <auth_shared_secret>.
# Health endpoint is always reachable so monitoring still works.
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class SharedSecretAuth(BaseHTTPMiddleware):
    def __init__(self, app, secret: str) -> None:
        super().__init__(app)
        self.secret = secret

    async def dispatch(self, request: Request, call_next):
        # Always allow: health, docs, openapi, and CORS preflights.
        path = request.url.path
        if (
            path in {"/api/health", "/docs", "/openapi.json", "/redoc"}
            or path.startswith("/docs")
            or request.method == "OPTIONS"
        ):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        else:
            token = request.headers.get("x-zenith-secret", "")
        if token != self.secret:
            return JSONResponse(
                {"detail": "Unauthorized — set Authorization: Bearer <auth_shared_secret>"},
                status_code=401,
            )
        return await call_next(request)


if bool(settings.get("auth_enabled", False)) and settings.get("auth_shared_secret"):
    app.add_middleware(SharedSecretAuth, secret=settings.get("auth_shared_secret", ""))
    log.info("auth.enabled", kind="shared_secret")


class PasscodeLock(BaseHTTPMiddleware):
    """App-level passcode gate (separate from the deploy-time shared secret).
    Checked live per-request so it takes effect the moment a user sets a
    passcode, without a restart. Requests must carry X-Zenith-Unlock with the
    token issued by /api/lock/verify."""

    _ALLOW = {"/api/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        from app.api import lock as lock_api

        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path in self._ALLOW
            or path.startswith("/docs")
            or path.startswith("/api/lock/")  # status/verify/set/disable stay reachable
            or path.startswith("/api/share/")  # public read-only shared-conversation links
            or not path.startswith("/api/")
        ):
            return await call_next(request)
        if lock_api.is_locked() and not lock_api.token_valid(request.headers.get("x-zenith-unlock", "")):
            return JSONResponse({"detail": "Locked — unlock with your passcode."}, status_code=423)
        return await call_next(request)


app.add_middleware(PasscodeLock)


app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(agent.router)
app.include_router(export.router)
app.include_router(documents.router)
app.include_router(files.router)
app.include_router(graph.router)
app.include_router(digest.router)
app.include_router(automation.router)
app.include_router(folders.router)
app.include_router(schedules.router)
app.include_router(mcp.router)
app.include_router(upload.router)
app.include_router(voice.router)
app.include_router(system.router)
app.include_router(lock.router)
app.include_router(images.router)
app.include_router(sync.router)
app.include_router(routing.router)