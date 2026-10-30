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
    r"algorithm|"
    # Languages/tools named on their own ("why does my Rust borrow checker
    # ...") and SQL/shell — gaps found by `python -m evals routing`.
    r"rust|golang|java|kotlin|c\+\+|c#|ruby|php|sql|bash|zsh|powershell|shell script|"
    r"borrow checker|dockerfile|makefile|unit tests?|compiler|"
    r"select (?:\*|\w+(?:\s*,\s*\w+)+|distinct \w+) from|react component)\b",
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


def is_cloud_model(name: str) -> bool:
    """Ollama Cloud models run on Ollama's servers, not this machine. Their
    tags end in `cloud` (`gpt-oss:120b-cloud`, `glm-5.3:cloud`)."""
    tag = name.lower().rsplit(":", 1)[-1] if ":" in name else ""
    return tag == "cloud" or tag.endswith("-cloud")


# name -> Ollama-reported capabilities ("vision", "tools", "thinking", "embedding"...)
_model_caps: dict[str, frozenset[str]] = {}

# Roles a model can fill by what it *does*, when no name keyword matches
# (e.g. qwen3.5 handles images, but nothing in its name says so).
_CAPABILITY_FOR_ROLE = {"vision": "vision", "embedding": "embedding", "reasoning": "thinking"}

# name -> parameters in billions, as Ollama reports them (details.parameter_size),
# for tags like `llama3:latest` whose name carries no size.
_reported_params: dict[str, float] = {}


def _parse_reported(size: object) -> float | None:
    m = re.match(r"\s*([\d.]+)\s*([BMK])", str(size or ""), re.IGNORECASE)
    if not m:
        return None
    scale = {"B": 1.0, "M": 1e-3, "K": 1e-6}[m.group(2).upper()]
    return float(m.group(1)) * scale


def _params_b(name: str) -> float | None:
    from app.services.hardware_service import _parse_params_b

    try:
        parsed = _parse_params_b(name)
    except Exception:
        parsed = None
    return parsed if parsed is not None else _reported_params.get(name)


# Comfortable and tight both fit — among those, size decides.
_FIT_RANK = {"comfortable": 0, "tight": 0, "unknown": 1, "will_struggle": 2}
_budget_cache: list[float | None] = []


def _memory_budget_gb() -> float | None:
    """VRAM if there's a GPU, else RAM — the same budget setup_models and
    the Settings model cookbook use. Detected once per process."""
    if not _budget_cache:
        try:
            from app.services.hardware_service import detect_hardware

            hw = detect_hardware()
            gpu = hw.get("gpu") or {}
            _budget_cache.append(gpu.get("vram_gb") or hw.get("ram_gb"))
        except Exception:
            _budget_cache.append(None)
    return _budget_cache[0]


def _best_fit(names: list[str]) -> str:
    """Among several models matching a role, prefer the most capable one
    that fits this machine: best fit class first, then the most parameters.
    Before this, the first match in `ollama list` order won, so general chat
    could land on a 1B model with a 4B one installed. Stable for ties."""
    from app.services.hardware_service import _fit

    budget = _memory_budget_gb()

    def key(item: tuple[int, str]) -> tuple[int, float, int]:
        idx, name = item
        p = _params_b(name)
        return (_FIT_RANK[_fit(p, budget)], -(p or 0.0), idx)

    return min(enumerate(names), key=key)[1]


class ModelRegistry:
    """Caches `ollama list` for a few seconds so every keystroke doesn't re-hit it.

    `models()` returns LOCAL models only unless `route_to_cloud_models` is on:
    every automatic pick in the app (routing, fallbacks, titles, memory,
    digests, email) goes through here, and an installed cloud model used to
    win the 'general' keyword match, silently sending chats off the machine.
    A cloud model the user pins explicitly (role override or per-message
    pick) still works — see ModelRouter._match_capability."""

    def __init__(self, client: OllamaClient | None = None, ttl: float = 15.0):
        self.client = client or OllamaClient()
        self.ttl = ttl
        self._cache: list[str] = []
        self._fetched_at = 0.0

    async def all_models(self, force: bool = False) -> list[str]:
        if force or (time.time() - self._fetched_at) > self.ttl:
            try:
                raw = await self.client.list_models()
                self._cache = [m["name"] for m in raw]
                for m in raw:
                    reported = _parse_reported((m.get("details") or {}).get("parameter_size"))
                    if reported is not None:
                        _reported_params[m["name"]] = reported
                self._fetched_at = time.time()
                caps_of = getattr(self.client, "capabilities", None)
                if caps_of is not None:
                    for name in self._cache:
                        if name not in _model_caps and not is_cloud_model(name):
                            try:
                                _model_caps[name] = await caps_of(name)
                            except Exception:
                                _model_caps[name] = frozenset()
            except OllamaError:
                # Keep serving the stale cache (or empty list) rather than crash;
                # the caller surfaces a clear error if it ends up with nothing.
                pass
        return self._cache

    async def models(self, force: bool = False) -> list[str]:
        names = await self.all_models(force)
        if bool(settings.get("route_to_cloud_models", False)):
            return names
        return [n for n in names if not is_cloud_model(n)]


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
    ) -> str:
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
        # An explicitly pinned cloud model is the user's choice, so honour it
        # even though cloud models are filtered out of `installed`.
        if override and (override in installed or is_cloud_model(override)):
            return override

        keywords = settings.get("capability_keywords", {}).get(role, [])
        matches = [n for n in installed if any(kw in n.lower() for kw in keywords)]
        # "qwen" (general) also matches qwen2.5-coder and qwen2.5vl: keep
        # models claimed by a more specialised role out of this role's pool,
        # unless that would leave nothing.
        kw_map = settings.get("capability_keywords", {})
        specialised = [kw for r in ("vision", "code", "reasoning", "embedding") if r != role
                       for kw in kw_map.get(r, [])]
        own = [n for n in matches if not any(kw in n.lower() for kw in specialised)]
        if own:
            matches = own
        if matches:
            if role in ("embedding", "small_fast") or len(matches) == 1:
                return matches[0]
            return _best_fit(matches)
        cap = _CAPABILITY_FOR_ROLE.get(role)
        if cap:
            capable = [n for n in installed if cap in _model_caps.get(n, frozenset())]
            if capable:
                return capable[0] if len(capable) == 1 else _best_fit(capable)
        if role == "small_fast":
            # Name lists can't keep up with new releases; any local chat model
            # of ~2B parameters or less is a sensible quick-reply model.
            kw_map = settings.get("capability_keywords", {})
            other_kws = [kw for r in ("embedding", "vision", "code", "reasoning") for kw in kw_map.get(r, [])]
            small = [(p, n) for n in installed
                     if (p := _params_b(n)) is not None and p <= 2.0
                     and not any(kw in n.lower() for kw in other_kws)]
            if small:
                return max(small)[1]
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
                        # A semantic pick must clearly beat the runner-up, or
                        # near-ties ("summarise a novel" ~ code 0.60 vs
                        # general 0.58) flip the route on noise.
                        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
                        margin = float(settings.get("router_semantic_margin", 0.05))
                        if embedding_score - runner_up < margin:
                            embedding_role, embedding_score = None, 0.0
            except Exception as exc:
                log.debug("embedding.router_unavailable", error=str(exc))

        installed = await self.registry.models()
        if not installed:
            if await self.registry.all_models():
                raise OllamaError(
                    "No local models installed — only Ollama Cloud models, which Zenith won't use "
                    "automatically. Pull a local one (e.g. `ollama pull llama3.2:3b`), pin a cloud model "
                    "in Settings → Model routing, or enable 'Use cloud models for automatic routing'."
                )
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

        # Sticky only while the topic hasn't clearly moved: a confident
        # semantic match to a role the previous model doesn't serve breaks it
        # (a document question after a code turn stayed on the coder before).
        semantic_moved = bool(
            embedding_role
            and embedding_score >= float(settings.get("router_confidence_threshold", 0.55))
            and self._match_capability(embedding_role, installed) not in (None, history_last_model)
        )
        if (
            history_last_model
            and history_last_model in installed
            and not has_image
            and not has_video
            and not has_long_document
            and not text_hint
            and not semantic_moved
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
        signal = f"regex:{text_hint or 'general'}"
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
            confidence = round(float(embedding_score), 3)
            signal = f"embedding:{role}"

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
            match_confidence = confidence
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
                matched_signal=signal,
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