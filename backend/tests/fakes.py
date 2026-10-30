"""A scripted stand-in for Ollama, patched onto OllamaClient's methods so
every service (they all import the same class) talks to it with no
network. Tests queue the model's replies in order, or install a responder
that decides per call, then assert on what the code did with them."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from typing import Any

EMBED_DIM = 768


def fake_vector(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Bag-of-words hashed into `dim` buckets, L2-normalised: texts that
    share words are close, which is all retrieval ordering needs."""
    vec = [0.0] * dim
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeOllama:
    def __init__(self, models: tuple[str, ...] = ("llama3.2:3b", "qwen2.5-coder:7b", "nomic-embed-text")):
        self.models = list(models)
        self.replies: list[Any] = []
        self.responder: Callable[[str, list[dict], Any], Any] | None = None
        self.calls: list[dict] = []
        self.embed_calls = 0
        self.default_reply = "OK."

    # --- scripting ----------------------------------------------------------
    def queue(self, *replies: Any) -> FakeOllama:
        """Each reply is a str, a dict (sent as JSON), or an Exception to raise."""
        self.replies.extend(replies)
        return self

    def tool(self, name: str, **args: Any) -> FakeOllama:
        return self.queue({"tool": name, "args": args})

    def final(self, text: str) -> FakeOllama:
        return self.queue({"final": text})

    def _next_reply(self, model: str, messages: list[dict], fmt: Any) -> str:
        if self.responder is not None:
            reply = self.responder(model, messages, fmt)
        elif self.replies:
            reply = self.replies.pop(0)
        else:
            reply = self.default_reply
        if isinstance(reply, BaseException):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    def prompts(self) -> list[str]:
        """The last user message of every chat call, in order."""
        out = []
        for c in self.calls:
            users = [m["content"] for m in c["messages"] if m.get("role") == "user"]
            out.append(users[-1] if users else "")
        return out

    # --- patched OllamaClient methods ----------------------------------------
    def install(self, monkeypatch) -> FakeOllama:
        from app.services import ollama_client

        fake = self

        async def list_models(_self):
            return [{"name": m, "size": 1} for m in fake.models]

        async def chat_stream(_self, model, messages, images_b64=None, options=None, format=None, **_kw):
            fake.calls.append({"model": model, "messages": [dict(m) for m in messages],
                               "images": images_b64, "format": format, "options": options})
            text = fake._next_reply(model, messages, format)
            for piece in re.findall(r"\S+\s*|\s+", text):
                yield piece

        async def embeddings(_self, model, text):
            fake.embed_calls += 1
            return fake_vector(text)

        async def preload(_self, model):
            return None

        cls = ollama_client.OllamaClient
        monkeypatch.setattr(cls, "list_models", list_models)
        monkeypatch.setattr(cls, "chat_stream", chat_stream)
        monkeypatch.setattr(cls, "embeddings", embeddings)
        monkeypatch.setattr(cls, "preload", preload)
        return self
