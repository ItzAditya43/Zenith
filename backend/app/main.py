from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, system, upload, voice
from app.core.config import settings
from app.core.logging import get_logger
from app.db.storage import init_db
from app.services.attachments import sweep_orphans

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    interval = int(settings.get("upload_sweep_interval_seconds", 30 * 60))
    sweeper = asyncio.create_task(_orphan_sweeper(interval))
    # Track the last model used in this process so the router can be
    # "sticky" — see ModelRouter.decide() and the /api/route/preview docstring.
    app.state.last_route_model = None
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Cortex",
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
        ]
    return list(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Optional shared-secret auth (Tier 1 #8) ---
# Off by default. When enabled, callers must send
#   Authorization: Bearer <auth_shared_secret>
# on every /api/* request, or  X-Cortex-Secret: <auth_shared_secret>.
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
            token = request.headers.get("x-cortex-secret", "")
        if token != self.secret:
            return JSONResponse(
                {"detail": "Unauthorized — set Authorization: Bearer <auth_shared_secret>"},
                status_code=401,
            )
        return await call_next(request)


if bool(settings.get("auth_enabled", False)) and settings.get("auth_shared_secret"):
    app.add_middleware(SharedSecretAuth, secret=settings.get("auth_shared_secret", ""))
    log.info("auth.enabled", kind="shared_secret")


app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(voice.router)
app.include_router(system.router)