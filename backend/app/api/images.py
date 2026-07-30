"""Image generation endpoints (local Stable Diffusion, off by default).

  GET  /api/images/status    — {configured}
  POST /api/images/generate  — {prompt, negative?} -> {images: [base64 png, ...]}
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.services import image_service

log = get_logger(__name__)
router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/status")
async def status():
    return {"configured": image_service.is_configured()}


@router.post("/generate")
async def generate(body: dict):
    prompt = str(body.get("prompt", "")).strip()
    negative = str(body.get("negative", "")).strip()
    try:
        images = await image_service.generate(prompt, negative)
    except image_service.ImageGenError as exc:
        # 400 for config/prompt problems, 502 for upstream server failures —
        # both carry a user-facing message.
        code = 400 if "configured" in str(exc) or "required" in str(exc) else 502
        raise HTTPException(code, str(exc))
    return {"images": images}
