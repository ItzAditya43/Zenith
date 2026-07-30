"""Local image generation via a Stable Diffusion server (AUTOMATIC1111 /
Forge / SD.Next — the de-facto `/sdapi/v1/txt2img` contract). Off by default;
the user points `image_gen_url` at their own running SD server, keeping the
whole thing local and free, same posture as the Ollama dependency.

No SD server is bundled — generation is only available when the user has one
running, and every call degrades to a clear message when it isn't configured
or can't be reached.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class ImageGenError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(str(settings.get("image_gen_url", "")).strip())


async def generate(prompt: str, negative: str = "") -> list[str]:
    """Return base64-encoded PNG(s) for a prompt. Raises ImageGenError with a
    user-facing message if not configured / unreachable / the server errors."""
    url = str(settings.get("image_gen_url", "")).strip().rstrip("/")
    if not url:
        raise ImageGenError(
            "No image server configured. Set the Stable Diffusion server URL in "
            "Settings → Image generation (e.g. http://localhost:7860)."
        )
    if not prompt.strip():
        raise ImageGenError("A prompt is required.")

    steps = int(settings.get("image_gen_steps", 20))
    size = int(settings.get("image_gen_size", 512))
    payload = {
        "prompt": prompt,
        "negative_prompt": negative,
        "steps": steps,
        "width": size,
        "height": size,
    }
    timeout = httpx.Timeout(connect=5.0, read=float(settings.get("image_gen_timeout_seconds", 180)),
                            write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(f"{url}/sdapi/v1/txt2img", json=payload)
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise ImageGenError(
                f"Can't reach the image server at {url}. Is it running with its API enabled?"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ImageGenError(
                f"The image server returned {exc.response.status_code}. "
                "Check the model is loaded and the API is enabled (--api for AUTOMATIC1111)."
            ) from exc
        except httpx.ReadTimeout as exc:
            raise ImageGenError("The image server timed out while generating.") from exc
        images = resp.json().get("images", [])
        if not images:
            raise ImageGenError("The image server returned no image.")
        return images
