"""
ModelRouter — decides which locally-installed Ollama model handles a given
turn, using two signals:

  1. WHAT was attached (image / video-frame => vision, long document => a
     model with enough context, etc.) — a hard constraint.
  2. WHAT the text is asking for (code, math/reasoning, quick answer,
     general chat) — a soft preference, only applied when the hard
     constraint doesn't already decide it.

The router never hits the network to "ask" a model which model to use —
that would be slow and circular. It's a fast, transparent, rule-based
classifier over installed models, refreshed periodically from `ollama list`.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.services.ollama_client import OllamaClient, OllamaError

_CODE_HINTS = re.compile(
    r"```|\bdef \w+\(|\bclass \w+\b|\bfunction\s*\(|\bimport \w+|\bconsole\.log\(|"
    r"\b(?:bug|stack trace|traceback|regex|compile error|segfault|null pointer|"
    r"typescript|python|javascript|refactor this|write a script|write code|"
    r"write a (?:sorting|searching|graph|dynamic[- ]programming|recursive|"
    r"binary tree|linked list|hash|merge|quick|heap|bubble|insertion|"
    r"selection|radix|counting|topological|bfs|dfs|dijkstra)a-z0-9' ]{0,40}?algorithm|"
    r"write me a (?:sorting|searching|graph|recursive)?\s*(?:algorithm|function|method|class|program|script)|"
    r"sorting algorithm|search algorithm|graph algorithm|"
    r"implement a (?:sort|search|tree|graph|hash|queue|stack|linked[- ]list|binary)|"
    r"code (?:a|an|the|this|that)|"
    r"in (?:python|javascript|typescript|rust|go|java|c\+\+|c#|ruby|kotlin|swift)|"
    r"algorithm)\b",
    re.IGNORECASE,
)
_REASONING_HINTS = re.compile(
    r"\b(?:step by step|prove|derive|why does|explain the reasoning|solve|"
    r"logic puzzle|brain ?teaser|calculate|optimi[sz]e|algorithm complexity)\b",
    re.IGNORECASE,
)
_QUICK_HINTS = re.compile(
    r"^(?:hi|hey|hello|yo|sup|thanks|thank you|ok|okay|cool|nice|lol)\b[\s!.?]*$",
    re.IGNORECASE,
)


@dataclass
class RouteDecision:
    model: str
    role: str  # which capability bucket was used
    reason: str
    installed_models: list[str] = field(default_factory=list)


class ModelRegistry:
    """Caches `ollama list` for a few seconds so every keystroke doesn't re-hit it."""

    def __init__(self, client: OllamaClient | None = None, ttl: float = 15.0):
        self.client = client or OllamaClient()
        self.ttl = ttl
        self._cache: list[str] = []
        self._fetched_at = 0.0

    async def models(self, force: bool = False) -> list[str]:
        if force or (time.time() - self._fetched_at) > self.ttl:
            try:
                raw = await self.client.list_models()
                self._cache = [m["name"] for m in raw]
                self._fetched_at = time.time()
            except OllamaError:
                # Keep serving the stale cache (or empty list) rather than crash;
                # the caller surfaces a clear error if it ends up with nothing.
                pass
        return self._cache


class ModelRouter:
    def __init__(self, registry: ModelRegistry | None = None):
        self.registry = registry or ModelRegistry()

    def _match_capability(self, role: str, installed: list[str]) -> str | None:
        override = settings.get("model_overrides", {}).get(role)
        if override and override in installed:
            return override

        keywords = settings.get("capability_keywords", {}).get(role, [])
        for name in installed:
            lname = name.lower()
            if any(kw in lname for kw in keywords):
                return name
        return None

    async def decide(
        self,
        *,
        text: str,
        has_image: bool = False,
        has_video: bool = False,
        has_long_document: bool = False,
    ) -> RouteDecision:
        installed = await self.registry.models()
        if not installed:
            raise OllamaError(
                "No models found on this Ollama instance. Run `ollama pull llama3.2` "
                "(and `ollama pull llava` for images) then try again."
            )

        # --- hard constraints first: the input shape decides the bucket ---
        if has_image or has_video:
            model = self._match_capability("vision", installed)
            if model:
                return RouteDecision(
                    model=model,
                    role="vision",
                    reason="Image/video frames attached — routed to a vision-capable model.",
                    installed_models=installed,
                )
            # No vision model installed: fall through to general so the user
            # at least gets a text answer (e.g. "you attached an image but no
            # vision model is installed") instead of a hard failure.

        # --- soft preferences from the text itself ---
        role = "general"
        reason = "General conversation."
        if text and _CODE_HINTS.search(text):
            role, reason = "code", "Message looks code-related."
        elif text and _REASONING_HINTS.search(text):
            role, reason = "reasoning", "Message asks for multi-step reasoning/math."
        elif text and _QUICK_HINTS.match(text.strip()):
            role, reason = "small_fast", "Short/simple message — using a fast small model."

        model = self._match_capability(role, installed)
        if model:
            return RouteDecision(model=model, role=role, reason=reason, installed_models=installed)

        # Requested bucket not installed — fall back to general, then to
        # whatever exists at all so the app degrades instead of failing.
        fallback = self._match_capability("general", installed) or installed[0]
        return RouteDecision(
            model=fallback,
            role="general",
            reason=f"No model tagged for '{role}' is installed — fallback to '{fallback}'.",
            installed_models=installed,
        )
