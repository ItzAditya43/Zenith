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
        format: str | dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """
        Streams token chunks from `/api/chat`. If `images_b64` is provided it
        is attached to the *last* user message (Ollama's vision-model convention).

        `format` is passed straight through as Ollama's structured-output
        constraint: either the string "json" (loose — reply must be valid
        JSON) or a full JSON Schema dict (strict — reply must match that
        shape). Omitted entirely when not given, so this is a no-op for
        every existing caller and for any Ollama version too old to
        recognize the field (it's just an extra ignored JSON key to those).
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
        if format is not None:
            payload["format"] = format

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
        format: str | dict[str, Any] | None = None,
    ) -> str:
        """Non-streaming convenience wrapper — collects the full reply."""
        out = []
        async for piece in self.chat_stream(model, messages, images_b64, options, format):
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

    # --- Model management (pull / create / delete / show) ------------------

    async def _stream_progress(self, path: str, payload: dict) -> AsyncIterator[dict]:
        """Shared streamer for /api/pull and /api/create, both of which emit
        newline-delimited JSON progress objects. Yields each parsed object;
        raises OllamaError on connection failure. Uses no read timeout —
        pulling a multi-GB model legitimately takes a long time."""
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                async with client.stream("POST", f"{self.host}{path}", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
            except httpx.ConnectError as exc:
                raise OllamaError(
                    f"Can't reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc

    async def pull_model(self, name: str) -> AsyncIterator[dict]:
        """Stream `ollama pull <name>` progress objects
        ({status, digest?, total?, completed?})."""
        async for ev in self._stream_progress("/api/pull", {"name": name, "stream": True}):
            yield ev

    async def create_model(self, name: str, spec: dict) -> AsyncIterator[dict]:
        """Stream `ollama create <name>` using the structured create API
        ({from, system, adapter, template, parameters, ...}). `adapter` is
        the fine-tune / LoRA path — a GGUF adapter file or a directory Ollama
        can read. Only non-empty spec fields are forwarded."""
        payload = {"model": name, "stream": True}
        for key in ("from", "system", "adapter", "template", "quantize"):
            val = spec.get(key)
            if val:
                payload[key] = val
        if isinstance(spec.get("parameters"), dict) and spec["parameters"]:
            payload["parameters"] = spec["parameters"]
        async for ev in self._stream_progress("/api/create", payload):
            yield ev

    async def delete_model(self, name: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.request(
                    "DELETE", f"{self.host}/api/delete", json={"name": name}
                )
                resp.raise_for_status()
            except httpx.ConnectError as exc:
                raise OllamaError(
                    f"Can't reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise OllamaError(
                    f"Ollama couldn't delete '{name}' ({exc.response.status_code})."
                ) from exc

    async def show_model(self, name: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(f"{self.host}/api/show", json={"name": name})
                resp.raise_for_status()
                return resp.json()
            except httpx.ConnectError as exc:
                raise OllamaError(
                    f"Can't reach Ollama at {self.host}. Is `ollama serve` running?"
                ) from exc
            except httpx.HTTPStatusError as exc:
                raise OllamaError(
                    f"Ollama couldn't show '{name}' ({exc.response.status_code})."
                ) from exc