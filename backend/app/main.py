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
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Cortex", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only tool; tighten if you expose this beyond localhost
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(voice.router)
app.include_router(system.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}