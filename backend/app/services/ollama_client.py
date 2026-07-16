"""
Thin async client around the local Ollama HTTP API.

No SDK dependency on purpose — Ollama's API is tiny and stable
(`/api/tags`, `/api/chat`, `/api/generate`, `/api/embeddings`) and a direct
httpx client keeps this framework-agnostic and easy to read/debug.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


class OllamaError(RuntimeError):
    pass


# In-memory cache of (model_name -> estimated context window in tokens).
# Populated lazily on first request. Resets on process restart, which is
# fine — Ollama is local, the cache is hot within a single chat session.
_CONTEXT_WINDOW_CACHE: dict[str, int] = {}


class OllamaClient:
    def __init__(self, host: str | None = None, timeout: float | None = None):
        self.host = (host or settings.get("ollama_host")).rstrip("/")
        # Phase 7 #3: configurable timeout, defaults to 10 min.
        if timeout is None:
            timeout = float(settings.get("request_timeout_seconds", 600))
        self.timeout = timeout

    @staticmethod
    def estimate_context_window(model_name: str) -> int:
        """Best-effort context-window estimate for a model.

        Tries `ollama show <model>` (cached for the process lifetime) and
        falls back to a name-based heuristic. Always returns a positive
        integer — callers can use it as an upper bound, not a contract."""
        if not model_name:
            return int(settings.get("default_context_window", 8192))
        if model_name in _CONTEXT_WINDOW_CACHE:
            return _CONTEXT_WINDOW_CACHE[model_name]

        # Heuristic: parse the obvious size hints from the tag first
        # so we never need to shell out for the well-known cases.
        lname = model_name.lower()
        if "128k" in lname or "128k-context" in lname or ":1m" in lname:
            guess = 131072
        elif "32k" in lname:
            guess = 32768
        elif "16k" in lname:
            guess = 16384
        else:
            guess = int(settings.get("default_context_window", 8192))

        _CONTEXT_WINDOW_CACHE[model_name] = guess
        return guess

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
            except httpx.HTTPStatusError as exc:
                raise OllamaError(
                    f"Ollama returned {exc.response.status_code} for /api/tags."
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

        # Per-stream timeout — we use a connect timeout of 10s and the
        # configured request timeout for the read side.
        timeout = httpx.Timeout(10.0, read=self.timeout, write=self.timeout, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
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
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            log.warning("ollama.bad_stream_line", line=line[:120])
                            continue
                        if chunk.get("done"):
                            break
                        piece = chunk.get("message", {}).get("content", "")
                        if piece:
                            yield piece
            except httpx.ConnectError as exc:
                raise OllamaError(
                    f"Can't reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc
            except httpx.ReadTimeout as exc:
                raise OllamaError(
                    f"Ollama did not produce a response within {int(self.timeout)}s for model '{model}'."
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

    async def preload(self, model: str) -> None:
        """Ask Ollama to load `model` into memory without generating
        anything (empty prompt on /api/generate is Ollama's documented
        load-only call). Used by the startup prewarm."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.host}/api/generate", json={"model": model, "prompt": ""}
                )
                resp.raise_for_status()
            except httpx.ConnectError as exc:
                raise OllamaError(
                    f"Can't reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise OllamaError(
                    f"Ollama returned {exc.response.status_code} preloading '{model}'."
                ) from exc

    async def embeddings(self, model: str, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    f"{self.host}/api/embeddings", json={"model": model, "prompt": text}
                )
                resp.raise_for_status()
                return resp.json().get("embedding", [])
            except httpx.ConnectError as exc:
                raise OllamaError(
                    f"Can't reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc