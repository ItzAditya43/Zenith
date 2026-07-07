"""
Thin async client around the local Ollama HTTP API.

No SDK dependency on purpose — Ollama's API is tiny and stable
(`/api/tags`, `/api/chat`, `/api/generate`, `/api/embeddings`) and a direct
httpx client keeps this framework-agnostic and easy to read/debug.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, host: str | None = None):
        self.host = (host or settings.get("ollama_host")).rstrip("/")

    async def list_models(self) -> list[dict[str, Any]]:
        """Returns raw model entries from `GET /api/tags` (name, size, etc.)."""
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{self.host}/api/tags")
                resp.raise_for_status()
            except httpx.ConnectError as exc:
                raise OllamaError(
                    f"Can't reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc
            return resp.json().get("models", [])

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        images_b64: list[str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """
        Streams token chunks from `/api/chat`. If `images_b64` is provided it
        is attached to the *last* user message (Ollama's vision-model convention).
        """
        payload_messages = [dict(m) for m in messages]
        if images_b64:
            for m in reversed(payload_messages):
                if m["role"] == "user":
                    m["images"] = images_b64
                    break

        payload = {
            "model": model,
            "messages": payload_messages,
            "stream": True,
            "options": options or {},
        }

        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream(
                    "POST", f"{self.host}/api/chat", json=payload
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise OllamaError(
                            f"Ollama returned {resp.status_code} for model '{model}': "
                            f"{body.decode(errors='ignore')[:300]}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        if chunk.get("done"):
                            break
                        piece = chunk.get("message", {}).get("content", "")
                        if piece:
                            yield piece
            except httpx.ConnectError as exc:
                raise OllamaError(
                    f"Can't reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        images_b64: list[str] | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Non-streaming convenience wrapper — collects the full reply."""
        out = []
        async for piece in self.chat_stream(model, messages, images_b64, options):
            out.append(piece)
        return "".join(out)

    async def embeddings(self, model: str, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.host}/api/embeddings", json={"model": model, "prompt": text}
            )
            resp.raise_for_status()
            return resp.json().get("embedding", [])
