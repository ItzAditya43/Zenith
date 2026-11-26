"""API model providers alongside Ollama.

Zenith reaches models through one client (`OllamaClient`). A model name of
the form ``<provider_id>::<model>`` (``openai::gpt-4.1``,
``anthropic::claude-opus-5-5``, ``lmstudio::qwen2.5-7b``) is routed to that
provider instead of Ollama; every other name still goes to Ollama. So chat,
agent mode, research, RAG, memory and the rest work with API models without
each one knowing providers exist. ``::`` never appears in an Ollama name.

Two kinds of provider:

- ``openai``: anything that speaks the OpenAI Chat Completions format,
  which covers OpenAI, OpenRouter, Groq, DeepSeek, Mistral, Together, xAI,
  Google Gemini's compatible endpoint, and local servers (LM Studio,
  llama.cpp, vLLM). Plain HTTP.
- ``anthropic``: Claude, through the official ``anthropic`` SDK.

Providers live in config under ``providers`` with API keys encrypted at
rest (crypto_service). The config API never returns them; the providers API
returns ``has_key`` instead of the key.

Privacy: a provider whose URL is not on this machine or private network is
"remote". Its models are treated like Ollama cloud models: never picked by
automatic routing unless you turn that on, only used when you pin or choose
one. A local server (LM Studio on localhost) counts as local.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

SEP = "::"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

# Ready-made entries for the add-provider form. `kind` picks the client.
PRESETS: list[dict[str, Any]] = [
    {"id": "openai", "name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "needs_key": True,
     "key_url": "https://platform.openai.com/api-keys"},
    {"id": "anthropic", "name": "Anthropic (Claude)", "kind": "anthropic", "base_url": "https://api.anthropic.com",
     "needs_key": True, "key_url": "https://platform.claude.com/settings/keys",
     "default_models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]},
    {"id": "gemini", "name": "Google Gemini", "kind": "openai",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "needs_key": True,
     "key_url": "https://aistudio.google.com/apikey"},
    {"id": "openrouter", "name": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1",
     "needs_key": True, "key_url": "https://openrouter.ai/keys"},
    {"id": "groq", "name": "Groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1", "needs_key": True,
     "key_url": "https://console.groq.com/keys"},
    {"id": "deepseek", "name": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com/v1",
     "needs_key": True, "key_url": "https://platform.deepseek.com/api_keys"},
    {"id": "mistral", "name": "Mistral", "kind": "openai", "base_url": "https://api.mistral.ai/v1", "needs_key": True,
     "key_url": "https://console.mistral.ai/api-keys"},
    {"id": "xai", "name": "xAI (Grok)", "kind": "openai", "base_url": "https://api.x.ai/v1", "needs_key": True,
     "key_url": "https://console.x.ai"},
    {"id": "together", "name": "Together AI", "kind": "openai", "base_url": "https://api.together.xyz/v1",
     "needs_key": True, "key_url": "https://api.together.ai/settings/api-keys"},
    {"id": "lmstudio", "name": "LM Studio (local)", "kind": "openai", "base_url": "http://localhost:1234/v1",
     "needs_key": False},
    {"id": "llamacpp", "name": "llama.cpp server (local)", "kind": "openai", "base_url": "http://localhost:8080/v1",
     "needs_key": False},
    {"id": "vllm", "name": "vLLM (local)", "kind": "openai", "base_url": "http://localhost:8000/v1", "needs_key": False},
]


class ProviderError(RuntimeError):
    """A provider call failed."""


class ProviderBlocked(ProviderError):
    """Zenith itself refused the call (local-only mode, spend limit)."""


# --- storage -------------------------------------------------------------------

def _all() -> list[dict]:
    raw = settings.get("providers") or []
    return [p for p in raw if isinstance(p, dict) and p.get("id")]


def get(provider_id: str) -> dict | None:
    return next((p for p in _all() if p["id"] == provider_id), None)


def _key(p: dict) -> str:
    from app.services.crypto_service import decrypt
    return decrypt(p.get("api_key") or "")


def is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "host.docker.internal") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def public(p: dict) -> dict:
    """A provider as the UI may see it: no key, just whether one is set."""
    return {
        "id": p["id"], "name": p.get("name") or p["id"], "kind": p.get("kind", "openai"),
        "base_url": p.get("base_url", ""), "enabled": p.get("enabled", True),
        "has_key": bool(p.get("api_key")), "models": p.get("models") or [],
        "local": is_local_url(p.get("base_url", "")),
        "roles": p.get("roles") or [], "price_in": p.get("price_in"), "price_out": p.get("price_out"),
        "monthly_limit": p.get("monthly_limit"),
    }


def list_public() -> list[dict]:
    return [public(p) for p in _all()]


def save(entry: dict) -> dict:
    """Create or update a provider. An empty or missing api_key on update
    keeps the stored one; send api_key=None-like "" with clear_key to remove."""
    from app.services.crypto_service import encrypt

    pid = str(entry.get("id") or "").strip().lower()
    if not _ID_RE.match(pid):
        raise ProviderError("The provider id must be lowercase letters, digits, - or _ (max 32).")
    kind = entry.get("kind", "openai")
    if kind not in ("openai", "anthropic"):
        raise ProviderError("Unknown provider type.")
    base_url = str(entry.get("base_url") or "").strip().rstrip("/")
    if not re.match(r"^https?://", base_url):
        raise ProviderError("The base URL must start with http:// or https://.")
    if not is_local_url(base_url) and base_url.startswith("http://"):
        raise ProviderError("Use https:// for providers that aren't on this machine, so your API key isn't sent in the clear.")
    providers = _all()
    old = next((p for p in providers if p["id"] == pid), None)
    new = {
        "id": pid,
        "name": str(entry.get("name") or pid)[:60],
        "kind": kind,
        "base_url": base_url,
        "enabled": bool(entry.get("enabled", True)),
        "models": [str(m)[:200] for m in (entry.get("models") or [])][:200],
        "api_key": old.get("api_key", "") if old else "",
        "roles": [str(r) for r in (entry.get("roles") or []) if r][:10],
        "price_in": _num(entry.get("price_in")),
        "price_out": _num(entry.get("price_out")),
        "monthly_limit": _num(entry.get("monthly_limit")),
    }
    key = entry.get("api_key")
    if isinstance(key, str) and key.strip():
        new["api_key"] = encrypt(key.strip())
    if entry.get("clear_key"):
        new["api_key"] = ""
    providers = [p for p in providers if p["id"] != pid] + [new]
    settings.update({"providers": providers})
    _models_cache.pop(pid, None)
    return public(new)


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def delete(provider_id: str) -> bool:
    providers = _all()
    keep = [p for p in providers if p["id"] != provider_id]
    if len(keep) == len(providers):
        return False
    settings.update({"providers": keep})
    _models_cache.pop(provider_id, None)
    return True


# --- names ---------------------------------------------------------------------

def split(name: str) -> tuple[dict, str] | None:
    """(provider, remote_model) when `name` is a provider model that's
    configured and enabled; None for Ollama names."""
    if not name or SEP not in name:
        return None
    pid, model = name.split(SEP, 1)
    p = get(pid)
    if not p or not p.get("enabled", True) or not model:
        return None
    return p, model


def is_provider_model(name: str) -> bool:
    return bool(name) and SEP in name


def is_remote_model(name: str) -> bool:
    """Provider model whose server isn't on this machine/network."""
    hit = split(name)
    if not hit:
        return is_provider_model(name)  # unknown/disabled provider: treat as remote
    return not is_local_url(hit[0].get("base_url", ""))


def guess_capabilities(name: str) -> frozenset[str]:
    m = name.lower()
    caps = {"completion"}
    if any(k in m for k in ("embed",)):
        return frozenset({"embedding"})
    if not any(k in m for k in ("instruct-0", "base")):
        caps.add("tools")
    if any(k in m for k in ("gpt-4o", "gpt-4.1", "gpt-5", "claude", "gemini", "vision", "-vl", "vl-", "llava",
                            "pixtral", "grok-4", "grok-2-vision", "qwen2.5-vl", "qwen3-vl", "llama-4")):
        caps.add("vision")
    if any(k in m for k in ("o1", "o3", "o4", "reason", "r1", "thinking", "claude-opus", "claude-sonnet", "claude-fable")):
        caps.add("thinking")
    return frozenset(caps)


# --- model lists ---------------------------------------------------------------

_models_cache: dict[str, tuple[float, list[str]]] = {}
_MODELS_TTL = 10 * 60


async def models_of(p: dict, force: bool = False) -> list[str]:
    """Models a provider offers. An explicit list saved on the provider
    wins (useful for OpenRouter's hundreds of models); otherwise asked from
    the provider and cached."""
    if p.get("models"):
        return list(p["models"])
    hit = _models_cache.get(p["id"])
    if hit and not force and time.time() - hit[0] < _MODELS_TTL:
        return hit[1]
    if p.get("kind") == "anthropic":
        names = await _anthropic_models(p)
    else:
        names = await _openai_models(p)
    _models_cache[p["id"]] = (time.time(), names)
    return names


async def all_models() -> list[dict[str, Any]]:
    """Every enabled provider's models as Ollama-style entries, for merging
    into the installed-model list. A provider that fails is skipped."""
    out: list[dict[str, Any]] = []
    for p in _all():
        if not p.get("enabled", True):
            continue
        try:
            names = await models_of(p)
        except Exception as exc:  # one broken provider never hides the rest
            log.info("providers.list_failed", provider=p["id"], error=str(exc)[:200])
            continue
        for n in names:
            out.append({"name": f"{p['id']}{SEP}{n}", "provider": p["id"], "provider_name": p.get("name"),
                        "remote": not is_local_url(p.get("base_url", "")), "size": 0})
    return out


# --- OpenAI-compatible -----------------------------------------------------------

def _headers(p: dict) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = _key(p)
    if key:
        h["Authorization"] = f"Bearer {key}"
    if "openrouter.ai" in p.get("base_url", ""):
        h["X-Title"] = "Zenith"
    return h


def _err(p: dict, status: int, body: str) -> ProviderError:
    detail = body[:300]
    try:
        j = json.loads(body)
        e = j.get("error") if isinstance(j, dict) else None
        detail = (e.get("message") if isinstance(e, dict) else e) or j.get("message") or detail
    except (ValueError, AttributeError):
        pass
    hint = {401: "the API key was rejected", 403: "access denied", 404: "model or endpoint not found",
            402: "the account needs credits", 429: "rate limited or out of quota"}.get(status, "")
    return ProviderError(f"{p.get('name', p['id'])} returned {status}{f' ({hint})' if hint else ''}: {detail}")


async def _openai_models(p: dict) -> list[str]:
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get(f"{p['base_url']}/models", headers=_headers(p))
        except httpx.HTTPError as exc:
            raise ProviderError(f"Can't reach {p.get('name', p['id'])} at {p['base_url']}.") from exc
    if r.status_code != 200:
        raise _err(p, r.status_code, r.text)
    data = r.json()
    items = data.get("data") if isinstance(data, dict) else data
    names = sorted({str(m.get("id")) for m in (items or []) if isinstance(m, dict) and m.get("id")})
    return names


def _image_mime(b64: str) -> str:
    head = base64.b64decode(b64[:32] + "=" * (-len(b64[:32]) % 4), validate=False)[:12]
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _openai_messages(messages: list[dict], images_b64: list[str] | None) -> list[dict]:
    out = []
    for m in messages:
        role = m.get("role", "user")
        if role not in ("system", "user", "assistant", "tool"):
            role = "user"
        out.append({"role": role, "content": m.get("content") or ""})
    if images_b64:
        for m in reversed(out):
            if m["role"] == "user":
                parts: list[dict] = [{"type": "text", "text": m["content"]}]
                parts += [{"type": "image_url", "image_url": {"url": f"data:{_image_mime(b)};base64,{b}"}} for b in images_b64]
                m["content"] = parts
                break
    return out


def _format_instruction(fmt: Any) -> str:
    if fmt is None:
        return ""
    if fmt == "json":
        return "Reply with a single valid JSON object and nothing else."
    return ("Reply with a single JSON object matching this JSON Schema, and nothing else:\n"
            + json.dumps(fmt))


async def openai_stream(p: dict, model: str, messages: list[dict], images_b64: list[str] | None = None,
                        options: dict | None = None, fmt: Any = None, emit_thinking: bool = False,
                        timeout: float = 600, usage: dict | None = None) -> AsyncIterator[str]:
    from app.services.ollama_client import ThinkingDelta

    body: dict[str, Any] = {"model": model, "messages": _openai_messages(messages, images_b64), "stream": True}
    if usage is not None and not is_local_url(p.get("base_url", "")):
        body["stream_options"] = {"include_usage": True}  # hosted APIs report real token counts
    opts = options or {}
    if "temperature" in opts:
        body["temperature"] = opts["temperature"]
    if opts.get("num_predict"):
        body["max_tokens"] = int(opts["num_predict"])
    if fmt is not None:
        # JSON mode is widely supported; a schema is given as an instruction
        # too, since not every compatible server implements json_schema.
        body["response_format"] = {"type": "json_object"}
        body["messages"] = [{"role": "system", "content": _format_instruction(fmt)}] + body["messages"]
    t = httpx.Timeout(15.0, read=timeout, write=60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=t) as c:
        try:
            async with c.stream("POST", f"{p['base_url']}/chat/completions", headers=_headers(p), json=body) as r:
                if r.status_code != 200:
                    raise _err(p, r.status_code, (await r.aread()).decode(errors="ignore"))
                async for line in r.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    u = chunk.get("usage")
                    if usage is not None and isinstance(u, dict) and u.get("completion_tokens") is not None:
                        usage["input"] = int(u.get("prompt_tokens") or 0)
                        usage["output"] = int(u.get("completion_tokens") or 0)
                    for ch in chunk.get("choices") or []:
                        delta = ch.get("delta") or {}
                        think = delta.get("reasoning_content") or delta.get("reasoning")
                        if emit_thinking and isinstance(think, str) and think:
                            yield ThinkingDelta(think)
                        piece = delta.get("content")
                        if isinstance(piece, str) and piece:
                            yield piece
        except httpx.ConnectError as exc:
            raise ProviderError(f"Can't reach {p.get('name', p['id'])} at {p['base_url']}.") from exc
        except httpx.ReadTimeout as exc:
            raise ProviderError(f"{p.get('name', p['id'])} didn't answer within {int(timeout)}s.") from exc


async def openai_tools(p: dict, model: str, messages: list[dict], tools: list[dict], timeout: float = 600) -> dict:
    body = {"model": model, "messages": _openai_messages(messages, None), "tools": tools, "stream": False}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=timeout)) as c:
        try:
            r = await c.post(f"{p['base_url']}/chat/completions", headers=_headers(p), json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Can't reach {p.get('name', p['id'])} at {p['base_url']}.") from exc
    if r.status_code != 200:
        raise _err(p, r.status_code, r.text)
    msg = ((r.json().get("choices") or [{}])[0]).get("message") or {}
    calls = [{"function": {"name": tc.get("function", {}).get("name", ""),
                           "arguments": tc.get("function", {}).get("arguments", "{}")}}
             for tc in (msg.get("tool_calls") or [])]
    return {"content": msg.get("content") or "", "tool_calls": calls}


async def openai_embed(p: dict, model: str, text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            r = await c.post(f"{p['base_url']}/embeddings", headers=_headers(p), json={"model": model, "input": text})
        except httpx.HTTPError as exc:
            raise ProviderError(f"Can't reach {p.get('name', p['id'])}.") from exc
    if r.status_code != 200:
        raise _err(p, r.status_code, r.text)
    data = r.json().get("data") or [{}]
    return list(data[0].get("embedding") or [])


# --- Anthropic (Claude) ----------------------------------------------------------

# Models where Anthropic recommends opting in to server-side refusal
# fallbacks: a declined request is re-run on a fallback model in the same call.
_FALLBACK_MODELS = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _anthropic_client(p: dict):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise ProviderError("The anthropic package isn't installed.") from exc
    key = _key(p)
    if not key:
        raise ProviderError("Add an Anthropic API key in Settings → Providers.")
    kwargs: dict[str, Any] = {"api_key": key}
    if p.get("base_url") and p["base_url"].rstrip("/") != "https://api.anthropic.com":
        kwargs["base_url"] = p["base_url"]
    return anthropic, anthropic.AsyncAnthropic(**kwargs)


def _anthropic_messages(messages: list[dict], images_b64: list[str] | None, fmt: Any) -> tuple[str, list[dict]]:
    """Claude takes the system prompt separately and wants alternating
    turns starting with the user; merge accordingly."""
    system_parts = [str(m.get("content") or "") for m in messages if m.get("role") == "system"]
    instr = _format_instruction(fmt)
    if instr:
        system_parts.append(instr)
    turns: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        role = "assistant" if role == "assistant" else "user"
        text = str(m.get("content") or "")
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n\n" + text
        else:
            turns.append({"role": role, "content": text})
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": "(continue)"})
    if images_b64:
        for t in reversed(turns):
            if t["role"] == "user":
                blocks: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": _image_mime(b), "data": b}}
                                      for b in images_b64]
                blocks.append({"type": "text", "text": t["content"] or "(image)"})
                t["content"] = blocks
                break
    return "\n\n".join(s for s in system_parts if s), turns


async def _anthropic_models(p: dict) -> list[str]:
    anthropic, client = _anthropic_client(p)
    try:
        page = await client.models.list(limit=100)
        names = [m.id for m in page.data]
    except anthropic.AuthenticationError as exc:
        raise ProviderError("Anthropic rejected the API key.") from exc
    except anthropic.APIConnectionError as exc:
        raise ProviderError("Can't reach the Anthropic API.") from exc
    except anthropic.APIStatusError as exc:
        raise ProviderError(f"Anthropic returned {exc.status_code}: {exc.message}") from exc
    preset = next((x for x in PRESETS if x["id"] == "anthropic"), {})
    return names or list(preset.get("default_models", []))


def _anthropic_call_kwargs(model: str, system: str, turns: list[dict], max_tokens: int, emit_thinking: bool) -> dict:
    kw: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": turns}
    if system:
        kw["system"] = system
    if emit_thinking:
        # Readable reasoning summaries for the live "thinking" view. Without
        # this, current models still think but return empty thinking text.
        kw["thinking"] = {"type": "adaptive", "display": "summarized"}
    if model in _FALLBACK_MODELS:
        kw["betas"] = [_FALLBACK_BETA]
        kw["fallbacks"] = "default"
    return kw


def _anthropic_error(anthropic, exc: Exception) -> ProviderError:
    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderError("Anthropic rejected the API key.")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError("Anthropic rate limit reached. Try again shortly.")
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderError(f"Anthropic returned {exc.status_code}: {exc.message}")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("Can't reach the Anthropic API.")
    return ProviderError(str(exc))


async def anthropic_stream(p: dict, model: str, messages: list[dict], images_b64: list[str] | None = None,
                           options: dict | None = None, fmt: Any = None, emit_thinking: bool = False,
                           usage: dict | None = None) -> AsyncIterator[str]:
    from app.services.ollama_client import ThinkingDelta

    anthropic, client = _anthropic_client(p)
    system, turns = _anthropic_messages(messages, images_b64, fmt)
    max_tokens = int((options or {}).get("num_predict") or 32000)
    kw = _anthropic_call_kwargs(model, system, turns, max_tokens, emit_thinking)
    try:
        async with client.beta.messages.stream(**kw) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield event.delta.text
                    elif event.delta.type == "thinking_delta" and emit_thinking and event.delta.thinking:
                        yield ThinkingDelta(event.delta.thinking)
            final = await stream.get_final_message()
            if usage is not None and getattr(final, "usage", None) is not None:
                usage["input"] = int(final.usage.input_tokens or 0)
                usage["output"] = int(final.usage.output_tokens or 0)
            if final.stop_reason == "refusal":
                yield "\n\n(Claude declined this request.)"
    except anthropic.APIError as exc:
        raise _anthropic_error(anthropic, exc) from exc


async def anthropic_tools(p: dict, model: str, messages: list[dict], tools: list[dict]) -> dict:
    anthropic, client = _anthropic_client(p)
    system, turns = _anthropic_messages(messages, None, None)
    claude_tools = []
    for t in tools:
        fn = t.get("function", t)
        claude_tools.append({"name": fn.get("name"), "description": fn.get("description", ""),
                             "input_schema": fn.get("parameters") or {"type": "object", "properties": {}}})
    kw = _anthropic_call_kwargs(model, system, turns, 16000, False)
    kw["tools"] = claude_tools
    try:
        msg = await client.beta.messages.create(**kw)
    except anthropic.APIError as exc:
        raise _anthropic_error(anthropic, exc) from exc
    text = "".join(b.text for b in msg.content if b.type == "text")
    calls = [{"function": {"name": b.name, "arguments": b.input}} for b in msg.content if b.type == "tool_use"]
    return {"content": text, "tool_calls": calls[:1]}


# --- dispatch used by OllamaClient -------------------------------------------------

async def stream(name: str, messages: list[dict], images_b64: list[str] | None, options: dict | None, fmt: Any,
                 emit_thinking: bool, timeout: float) -> AsyncIterator[str]:
    hit = split(name)
    if not hit:
        raise ProviderError(f"No enabled provider for '{name}'. Check Settings → Providers.")
    p, model = hit
    _guard(p, name)
    from app.services import spend_service

    usage: dict = {}
    out: list[str] = []
    try:
        if p.get("kind") == "anthropic":
            gen = anthropic_stream(p, model, messages, images_b64, options, fmt, emit_thinking, usage=usage)
        else:
            gen = openai_stream(p, model, messages, images_b64, options, fmt, emit_thinking, timeout, usage=usage)
        async for piece in gen:
            if type(piece).__name__ != "ThinkingDelta":
                out.append(str(piece))
            yield piece
    finally:
        prompt_text = "".join(str(m.get("content") or "") for m in messages)
        reported = "output" in usage
        try:
            spend_service.record(p, model, usage.get("input", spend_service.estimate_tokens(prompt_text)),
                                 usage.get("output", spend_service.estimate_tokens("".join(out))), reported)
        except Exception as exc:  # noqa: BLE001 — usage accounting never breaks a reply
            log.debug("providers.usage_record_failed", error=str(exc))


async def tools_call(name: str, messages: list[dict], tools: list[dict], timeout: float) -> dict:
    hit = split(name)
    if not hit:
        raise ProviderError(f"No enabled provider for '{name}'.")
    p, model = hit
    _guard(p, name)
    from app.services import spend_service

    if p.get("kind") == "anthropic":
        res = await anthropic_tools(p, model, messages, tools)
    else:
        res = await openai_tools(p, model, messages, tools, timeout)
    try:
        spend_service.record(p, model, spend_service.estimate_tokens(json.dumps(messages)),
                             spend_service.estimate_tokens(json.dumps(res)), False)
    except Exception as exc:  # noqa: BLE001
        log.debug("providers.usage_record_failed", error=str(exc))
    return res


def _guard(p: dict, name: str) -> None:
    """Local-only mode refuses remote providers outright; a monthly limit
    stops calls once reached."""
    from app.services import spend_service
    from app.services.router import manual_allowed

    if not manual_allowed(name):
        raise ProviderBlocked("Local-only mode is on, so models on other companies' servers can't be used. "
                            "Change it in Settings → Model routing.")
    spend_service.check_limit(p)


async def embed(name: str, text: str) -> list[float]:
    hit = split(name)
    if not hit:
        raise ProviderError(f"No enabled provider for '{name}'.")
    p, model = hit
    if p.get("kind") == "anthropic":
        raise ProviderError("Anthropic doesn't offer embedding models. Use a local one from Ollama.")
    return await openai_embed(p, model, text)
