"""A guided connection check for an API provider (saved or not yet saved).

Runs the steps a user would otherwise debug by hand, stopping at the
first one that fails and explaining what to do next:

  address    the base URL is well formed (and https unless it's local)
  reach      the server answers
  key        the key is accepted (skipped for local servers without one)
  models     it lists at least one model
  chat       a real, tiny streamed reply comes back (with time to first token)
  tools      (thorough) tool calling works on that model
  embeddings (thorough) an embedding model returns vectors, if one is listed

Each model also gets its likely capabilities (vision, tools, thinking,
embeddings) from its name. The key is never returned or logged.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

from app.core.logging import get_logger
from app.services import providers

log = get_logger(__name__)

LOCAL_HINTS = {
    "localhost:1234": "Open LM Studio → Developer → Start server (port 1234), and load a model.",
    "localhost:8080": "Start llama.cpp's server, e.g. `llama-server -m model.gguf --port 8080`.",
    "localhost:8000": "Start vLLM, e.g. `vllm serve <model> --port 8000`.",
}


def _fix_for(p: dict, error: str) -> str:
    e = error.lower()
    preset = next((x for x in providers.PRESETS if x["base_url"] == p.get("base_url")), {})
    key_url = preset.get("key_url")
    if "rejected" in e or " 401" in e or "invalid api key" in e or "authentication" in e:
        return f"Paste a fresh key{f' from {key_url}' if key_url else ''}; check it wasn't cut off when copying."
    if " 402" in e or "credit" in e or "billing" in e or "insufficient" in e:
        return "The account has no credit. Add a payment method or credits on the provider's site, then check again."
    if " 429" in e or "rate limit" in e or "quota" in e:
        return "You've hit a rate limit or quota. Wait a minute, or raise the limit in the provider's dashboard."
    if " 404" in e or "not found" in e:
        return "Check the base URL — OpenAI-compatible servers usually end in /v1."
    if " 403" in e or "access denied" in e:
        return "The key works but isn't allowed to do this — check its permissions or project on the provider's site."
    if "can't reach" in e or "connect" in e or "timed out" in e:
        host = urlparse(p.get("base_url", "")).netloc
        for k, hint in LOCAL_HINTS.items():
            if k in host:
                return hint
        if providers.is_local_url(p.get("base_url", "")):
            return "Make sure the local server is running and listening on that port."
        return "Check the address and your internet connection; some networks block AI APIs."
    return "Check the settings above and try again."


def caps_of(name: str) -> list[str]:
    return sorted(providers.guess_capabilities(name) - {"completion"})


async def _stream_once(p: dict, model: str) -> tuple[str, float]:
    msgs = [{"role": "user", "content": "Reply with the single word OK."}]
    t0 = time.perf_counter()
    first = None
    out = []
    gen = (providers.anthropic_stream(p, model, msgs, None, {"num_predict": 16})
           if p.get("kind") == "anthropic" else
           providers.openai_stream(p, model, msgs, None, {"num_predict": 16}, timeout=60))
    async for piece in gen:
        if type(piece).__name__ == "ThinkingDelta":
            continue
        if first is None:
            first = time.perf_counter()
        out.append(str(piece))
        if len("".join(out)) > 40:
            break
    return "".join(out).strip(), ((first or time.perf_counter()) - t0) * 1000


def _pick_chat_model(models: list[str]) -> str | None:
    chat = [m for m in models if "embedding" not in providers.guess_capabilities(m)
            and not re.search(r"(whisper|tts|dall-e|image|moderation|rerank)", m, re.I)]
    if not chat:
        return None
    for pref in ("mini", "flash", "haiku", "small", "8b", "7b"):
        hit = next((m for m in chat if pref in m.lower()), None)
        if hit:
            return hit  # a small, cheap model keeps the check fast and nearly free
    return chat[0]


async def check(entry: dict, model: str | None = None, thorough: bool = False) -> dict[str, Any]:
    """`entry` is either {"id": <saved id>} or a full unsaved provider with
    a plain `api_key`. Returns {ok, steps, models, chat_model, next}."""
    from app.services.crypto_service import encrypt

    saved = providers.get(entry.get("id", "")) if entry.get("id") else None
    if saved and not entry.get("base_url"):
        p = dict(saved)
    else:
        p = {"id": entry.get("id") or "candidate", "name": entry.get("name") or "This provider",
             "kind": entry.get("kind", "openai"), "base_url": str(entry.get("base_url") or "").strip().rstrip("/"),
             "api_key": encrypt(entry["api_key"].strip()) if (entry.get("api_key") or "").strip() else (saved or {}).get("api_key", "")}
    steps: list[dict] = []

    def step(sid: str, label: str, ok: bool | None, detail: str = "", fix: str = "") -> bool:
        steps.append({"id": sid, "label": label, "ok": ok, "detail": detail, "fix": fix})
        return bool(ok)

    def done(next_text: str, models: list[dict] | None = None, chat_model: str | None = None) -> dict:
        ok = all(s["ok"] is not False for s in steps)
        return {"ok": ok, "steps": steps, "models": models or [], "chat_model": chat_model, "next": next_text}

    url = p["base_url"]
    local = providers.is_local_url(url)
    if not re.match(r"^https?://", url):
        step("address", "Address", False, url or "(empty)", "Start the address with https:// (or http:// for a server on this machine).")
        return done("Fix the address, then check again.")
    if not local and url.startswith("http://"):
        step("address", "Address", False, url, "Use https:// so your key isn't sent in the clear.")
        return done("Fix the address, then check again.")
    step("address", "Address", True, f"{'On this machine' if local else 'Remote'} · {urlparse(url).netloc}")

    needs_key = not local
    if needs_key and not p.get("api_key"):
        step("key", "API key", False, "No key entered.", _fix_for(p, "rejected"))
        return done("Add the API key, then check again.")

    try:
        names = await (providers._anthropic_models(p) if p.get("kind") == "anthropic" else providers._openai_models(p))  # noqa: SLF001
    except providers.ProviderError as exc:
        msg = str(exc)
        reach_failed = "can't reach" in msg.lower()
        step("reach", "Server answers", not reach_failed, "" if not reach_failed else msg, _fix_for(p, msg) if reach_failed else "")
        if not reach_failed:
            step("key", "API key", False, msg, _fix_for(p, msg))
        return done("Fix the step marked above, then check again.")
    step("reach", "Server answers", True)
    step("key", "API key", True, "Accepted" if p.get("api_key") else "Not needed for this server")
    if not names:
        step("models", "Models", False, "The server lists no models.",
             LOCAL_HINTS.get(urlparse(url).netloc, "Load or enable at least one model on the server."))
        return done("Load a model, then check again.")
    step("models", "Models", True, f"{len(names)} available")
    models = [{"name": n, "caps": caps_of(n)} for n in names[:500]]

    chat_model = model if model in names else _pick_chat_model(names)
    if not chat_model:
        step("chat", "Chat reply", None, "Only embedding or special-purpose models are listed; chat wasn't tested.")
        return done("This provider can be used for embeddings.", models)
    try:
        text, ttft = await _stream_once(p, chat_model)
        if not text:
            raise providers.ProviderError("The model returned an empty reply.")
        step("chat", "Chat reply", True, f"{chat_model} answered “{text[:30]}” · first token in {ttft / 1000:.1f}s")
    except Exception as exc:  # noqa: BLE001
        step("chat", "Chat reply", False, f"{chat_model}: {exc}", _fix_for(p, str(exc)))
        return done("The connection works but this model didn't answer — try another model or fix the step above.", models, chat_model)

    if thorough:
        tool = {"type": "function", "function": {"name": "get_time", "description": "Get the current time",
                                                 "parameters": {"type": "object", "properties": {}}}}
        try:
            fn = providers.anthropic_tools if p.get("kind") == "anthropic" else providers.openai_tools
            res = await fn(p, chat_model, [{"role": "user", "content": "What time is it? Use the tool."}], [tool])
            step("tools", "Tool calling", True, "The model called the tool." if res.get("tool_calls") else
                 "Accepted tools but didn't call one (fine for chat; agent mode may struggle).")
        except Exception as exc:  # noqa: BLE001
            step("tools", "Tool calling", None, f"Not supported here ({str(exc)[:120]}). Agent mode will use Zenith's own JSON protocol instead.")
        emb = next((n for n in names if "embedding" in providers.guess_capabilities(n)), None)
        if emb and p.get("kind") != "anthropic":
            try:
                vec = await providers.openai_embed(p, emb, "hello")
                step("embeddings", "Embeddings", bool(vec), f"{emb} · {len(vec)} dimensions")
            except Exception as exc:  # noqa: BLE001
                step("embeddings", "Embeddings", None, f"{emb}: {str(exc)[:120]}")
    remote_note = "" if local else " It runs on the provider's servers and may cost money per message; Zenith only uses it when you pick it."
    return done(f"Ready. Save it, then pick one of its models from any model menu.{remote_note}", models, chat_model)
