"""Embedding-based semantic router.

We embed a small set of example prompts per capability role (one-time,
cached on disk) and embed the incoming message at routing time, then
pick the role with the highest cosine similarity.

Backed by Ollama's `/api/embeddings` endpoint, so it runs fully local
and re-uses whatever embedding model the user has pulled. Falls back to
the regex router when no embedding model is installed/configured.
"""
from __future__ import annotations

import asyncio
import math
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ollama_client import OllamaClient, OllamaError

log = get_logger(__name__)


# Default seed prompts per role. Users can extend this in their config
# under `embedding_seed_prompts`.
_DEFAULT_SEED_PROMPTS: dict[str, list[str]] = {
    "code": [
        "write a function that sorts a list",
        "implement a binary search algorithm",
        "fix this stack trace",
        "refactor this Python class",
        "show me how to use a for loop in JavaScript",
        "why is this regex not matching",
        "explain the time complexity of this code",
    ],
    "reasoning": [
        "prove that the square root of 2 is irrational",
        "solve this step by step",
        "explain the logic behind this puzzle",
        "why does the sky appear blue",
        "calculate the derivative of this function",
    ],
    "vision": [
        "describe what is in this image",
        "what do you see in this picture",
        "summarize the contents of this photo",
    ],
    "small_fast": [
        "hi",
        "thanks",
        "ok",
        "yes",
        "no",
    ],
    "general": [
        "tell me a story",
        "what is the meaning of life",
        "summarize the history of the Roman empire",
        "explain quantum mechanics to a child",
        "give me a recipe for dinner",
    ],
}


def _seed_prompts() -> dict[str, list[str]]:
    configured = settings.get("embedding_seed_prompts")
    if isinstance(configured, dict) and configured:
        return {**{k: v for k, v in _DEFAULT_SEED_PROMPTS.items() if k not in configured}, **configured}
    return dict(_DEFAULT_SEED_PROMPTS)


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class EmbeddingRouter:
    """Tries to pick a role by cosine similarity to seed prompts.

    This is intentionally very small and self-contained. The actual
    embedding model is whatever's in the user's `embedding` capability
    bucket (auto-classified by `ModelRouter`)."""

    CACHE_FILE = Path("data") / "embedding_seed_cache.json"

    def __init__(self, ollama: OllamaClient | None = None):
        self.ollama = ollama or OllamaClient()
        self._cache: dict[str, list[list[float]]] = {}
        self._loaded = False

    async def _ensure_cache(self, embed_model: str) -> dict[str, list[list[float]]]:
        if self._loaded and self._cache:
            return self._cache
        cache = {"model": embed_model, "vectors": {}}
        try:
            if self.CACHE_FILE.exists():
                import json
                cache = json.loads(self.CACHE_FILE.read_text())
                if cache.get("model") == embed_model and cache.get("vectors"):
                    self._cache = cache["vectors"]
                    self._loaded = True
                    return self._cache
        except Exception as exc:
            log.warning("embed.cache_read_failed", error=str(exc))

        # Build the cache from scratch.
        seeds = _seed_prompts()
        vectors: dict[str, list[list[float]]] = {}
        for role, prompts in seeds.items():
            role_vecs = []
            for p in prompts:
                try:
                    v = await self.ollama.embeddings(embed_model, p)
                    if v:
                        role_vecs.append(v)
                except OllamaError as exc:
                    log.warning("embed.embed_failed", role=role, error=str(exc))
            if role_vecs:
                vectors[role] = role_vecs

        self._cache = vectors
        self._loaded = True
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            import json
            self.CACHE_FILE.write_text(json.dumps({"model": embed_model, "vectors": vectors}))
        except Exception as exc:
            log.warning("embed.cache_write_failed", error=str(exc))
        return vectors

    async def rank(self, text: str, embed_model: str) -> list[tuple[str, float]] | None:
        """Returns a sorted list of (role, score) by cosine similarity.
        Returns None when embedding is unavailable so the caller can
        fall back to the regex router."""
        if not text or not text.strip():
            return None
        try:
            query = await self.ollama.embeddings(embed_model, text)
        except OllamaError as exc:
            log.warning("embed.query_failed", error=str(exc))
            return None
        if not query:
            return None
        cache = await self._ensure_cache(embed_model)
        if not cache:
            return None

        scores: list[tuple[str, float]] = []
        for role, vecs in cache.items():
            if not vecs:
                continue
            best = max(_cos(query, v) for v in vecs)
            scores.append((role, best))
        scores.sort(key=lambda r: r[1], reverse=True)
        return scores