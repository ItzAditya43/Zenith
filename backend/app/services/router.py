"""
ModelRouter — decides which locally-installed Ollama model handles a given
turn, using multiple signals:

  1. WHAT was attached (image / video-frame => vision, long document => a
     model with enough context, etc.) — a hard constraint.
  2. WHAT the text is asking for (code, math/reasoning, quick answer,
     general chat) — a soft preference, only applied when the hard
     constraint doesn't already decide it.
  3. STICKINESS — bias toward the previous turn's model when nothing
     new forces a re-route, so "explain that part" after a code turn
     doesn't bounce to `general`.
  4. CONTEXT WINDOW — if the conversation + attachments would overflow
     the chosen model's window, prefer a larger one.
  5. CONFIDENCE — emit a 0..1 score; the UI uses it to surface a
     "change?" affordance below the configured threshold.

The router never hits the network to "ask" a model which model to use —
that would be slow and circular. It's a fast, transparent, rule-based
classifier over installed models, refreshed periodically from `ollama list`.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ollama_client import OllamaClient, OllamaError

log = get_logger(__name__)

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
    confidence: float = 1.0  # 0..1 — UI shows "change?" under threshold
    installed_models: list[str] = field(default_factory=list)
    matched_signal: str = ""  # what drove the pick (regex / keyword / sticky / context)


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


# Above this confidence, the keyword/embedding match is considered strong
# enough that learned override history shouldn't fight it — this is meant
# to resolve ambiguous/weak picks, not overturn a confident one (e.g. the
# 0.95 hard vision constraint, or a very confident embedding match).
_LEARNED_OVERRIDE_CONFIDENCE_CEILING = 0.92


class ModelRouter:
    def __init__(self, registry: ModelRegistry | None = None):
        self.registry = registry or ModelRegistry()
        # Optional embedding-based router (lazy: set via set_embedder() so we
        # don't pay the import cost when no embedding model is configured).
        self._embedder = None

    def set_embedder(self, embedder) -> None:
        """Inject a callable (text) -> list[float]. Used for semantic
        routing when an embedding model is configured."""
        self._embedder = embedder

    def _apply_learned_override(
        self, role: str, model: str, confidence: float, installed: list[str]
    ) -> str | None:
        """If past manual overrides show a strong, repeated pattern of the
        user redirecting `role` decisions to a specific installed model, and
        the current pick's confidence isn't already high, prefer the
        learned model instead. Returns `model` unchanged when there's no
        history, the pattern isn't strong enough, the learned model isn't
        installed, or the current match is already confident — i.e. it
        degrades to exactly today's behavior in the absence of a clear
        override pattern."""
        if confidence >= _LEARNED_OVERRIDE_CONFIDENCE_CEILING:
            return model
        try:
            from app.db import storage
            learned = storage.dominant_override_model(role)
        except Exception as exc:
            log.debug("routing.learned_override_lookup_failed", role=role, error=str(exc))
            return model
        if learned and learned in installed and learned != model:
            log.info(
                "routing.learned_override_applied",
                role=role, original_model=model, learned_model=learned,
            )
            return learned
        return model

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

    @staticmethod
    def _estimate_chars(model_name: str) -> int:
        """Heuristic context-window estimate. We don't shell out to
        `ollama show` on every decide() — that's too slow for a chat
        router — but we *do* cache the result, so the first chat turn
        pays the cost and subsequent ones are instant."""
        from app.services.ollama_client import OllamaClient
        return OllamaClient.estimate_context_window(model_name)

    def _pick_by_context_window(
        self, role: str, installed: list[str], needed_chars: int
    ) -> str | None:
        """If a higher-context model is available in the same role bucket,
        prefer it when the conversation overflows the canonical model's
        window. Otherwise returns the canonical model for the role."""
        candidate = self._match_capability(role, installed)
        if not candidate:
            return None
        if needed_chars <= 0:
            return candidate
        cap = self._estimate_chars(candidate)
        if cap and needed_chars <= cap * 3:  # ~3 chars/token
            return candidate
        # Look for a "bigger" alternative in the same bucket.
        bigger = [m for m in installed if m != candidate and self._estimate_chars(m) > cap]
        if bigger:
            chosen = sorted(bigger, key=self._estimate_chars, reverse=True)[0]
            return chosen
        return candidate

    async def decide(
        self,
        *,
        text: str,
        has_image: bool = False,
        has_video: bool = False,
        has_long_document: bool = False,
        history_last_model: str | None = None,
        context_chars: int = 0,
    ) -> RouteDecision:
        # Tier 2 #1: try the embedding router first. If it produces a high-
        # confidence semantic match, prefer that over the regex signal so
        # nuanced prompts (e.g. "what does this Python error mean") route
        # correctly even when the regex doesn't fire.
        embedding_role = None
        embedding_score = 0.0
        if text and not has_image and not has_video:
            try:
                from app.services.embedding_router import EmbeddingRouter
                er = EmbeddingRouter()
                # Use the auto-classified embedding model from this router.
                embed_model = self._match_capability(
                    "embedding", await self.registry.models()
                )
                if embed_model:
                    ranked = await er.rank(text, embed_model)
                    if ranked:
                        embedding_role, embedding_score = ranked[0]
            except Exception as exc:
                log.debug("embedding.router_unavailable", error=str(exc))

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
                    confidence=0.95,
                    installed_models=installed,
                    matched_signal="attachment:image_or_video",
                )
            # No vision model installed: fall through to general so the user
            # at least gets a text answer (e.g. "you attached an image but no
            # vision model is installed") instead of a hard failure.

        # --- sticky routing (Tier 2 #2) ---
        # If we have a previous-turn model and the new message is plain text
        # with no fresh hard constraint, prefer staying on that model. This
        # only kicks in when the new text doesn't strongly suggest a
        # different bucket (we still let code/reasoning hints win).
        text_hint = ""
        if text:
            if _CODE_HINTS.search(text):
                text_hint = "code"
            elif _REASONING_HINTS.search(text):
                text_hint = "reasoning"
            elif _QUICK_HINTS.match(text.strip()):
                text_hint = "small_fast"

        if (
            history_last_model
            and history_last_model in installed
            and not has_image
            and not has_video
            and not has_long_document
            and not text_hint
        ):
            return RouteDecision(
                model=history_last_model,
                role="sticky",
                reason=f"Continuing with the model from your previous turn ({history_last_model}).",
                confidence=0.7,
                installed_models=installed,
                matched_signal="sticky:previous_turn",
            )

        # --- soft preferences from the text itself ---
        role = "general"
        reason = "General conversation."
        confidence = 0.9
        if text_hint == "code":
            role, reason = "code", "Message looks code-related."
        elif text_hint == "reasoning":
            role, reason = "reasoning", "Message asks for multi-step reasoning/math."
        elif text_hint == "small_fast":
            role, reason = "small_fast", "Short/simple message — using a fast small model."
        # If regex is silent but the semantic router has a confident match,
        # let the embedding pick the role. This is the "write me a Python
        # helper" case that the regex misses.
        elif (
            not text_hint
            and embedding_role
            and embedding_score >= float(settings.get("router_confidence_threshold", 0.55))
            and self._match_capability(embedding_role, installed)
        ):
            role = embedding_role
            reason = (
                f"Semantic match: your message is closest to other '{role}' prompts "
                f"(score {embedding_score:.2f})."
            )
            confidence = float(embedding_score)

        # --- context-window-aware pick (Tier 2 #3) ---
        if has_long_document or context_chars:
            candidate = self._pick_by_context_window(role, installed, context_chars)
            if candidate:
                context_reason = (
                    f"{reason} Picked a larger-context model to fit the attached document."
                    if candidate != self._match_capability(role, installed)
                    else reason
                )
                context_confidence = 0.85
                learned = self._apply_learned_override(
                    role, candidate, context_confidence, installed
                )
                if learned != candidate:
                    context_reason = (
                        f"{reason} Recent manual overrides show you prefer {learned} "
                        f"for '{role}' — using it."
                    )
                    candidate = learned
                return RouteDecision(
                    model=candidate,
                    role=role,
                    reason=context_reason,
                    confidence=context_confidence,
                    installed_models=installed,
                    matched_signal=f"context_window:needed={context_chars}",
                )

        model = self._match_capability(role, installed)
        if model:
            match_confidence = 0.9
            learned = self._apply_learned_override(role, model, match_confidence, installed)
            if learned != model:
                reason = (
                    f"{reason} Recent manual overrides show you prefer {learned} "
                    f"for '{role}' — using it."
                )
                model = learned
            return RouteDecision(
                model=model,
                role=role,
                reason=reason,
                confidence=match_confidence,
                installed_models=installed,
                matched_signal=f"regex:{role}",
            )

        # Requested bucket not installed — fall back to general, then to
        # whatever exists at all so the app degrades instead of failing.
        fallback = self._match_capability("general", installed) or installed[0]
        fallback_confidence = 0.6
        fallback_reason = f"No model tagged for '{role}' is installed — fallback to '{fallback}'."
        learned = self._apply_learned_override("general", fallback, fallback_confidence, installed)
        if learned != fallback:
            fallback_reason = (
                f"{fallback_reason} Recent manual overrides show you prefer {learned} "
                f"for 'general' — using it instead."
            )
            fallback = learned
        return RouteDecision(
            model=fallback,
            role="general",
            reason=fallback_reason,
            confidence=fallback_confidence,
            installed_models=installed,
            matched_signal="fallback",
        )