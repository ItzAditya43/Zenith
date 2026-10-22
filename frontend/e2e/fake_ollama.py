"""Deterministic stand-in for Ollama's HTTP API, for the Playwright suite.

Implements just what Zenith calls: /api/tags, /api/chat (NDJSON stream),
/api/embeddings, /api/generate (preload), /api/show. Replies are derived
from the request so tests can assert on them:

- plain chat -> "Echo: <first line of the user message>" plus
  " | docs: <names>" when retrieved document chunks were included;
- agent steps (a JSON-schema `format` is sent) -> write_file e2e.txt,
  then a final answer once the tool result (or a denial) comes back;
- anything else (titles, memory extraction) -> "[]".

Run: python fake_ollama.py [port]   (default 11555)
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = ["llama3.2:3b", "qwen2.5-coder:7b", "nomic-embed-text"]


def _vector(text: str, dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _reply(body: dict) -> str:
    messages = body.get("messages") or []
    users = [m.get("content", "") for m in messages if m.get("role") == "user"]
    last = users[-1] if users else ""
    if body.get("format") is not None:  # agent tool-selection step
        if last.startswith("Tool call denied"):
            return json.dumps({"final": "Okay, I skipped writing the file."})
        if last.startswith("Tool result for write_file"):
            return json.dumps({"final": "Wrote e2e.txt for you."})
        return json.dumps({"tool": "write_file", "args": {"path": "e2e.txt", "content": "hello from e2e"}})
    if "long-term memory" in last or "Facts:" in last or "title" in last.lower()[:200]:
        return "[]"
    first_line = last.split("\n", 1)[0][:80]
    docs = sorted(set(re.findall(r"\[From '([^']+)'\]", last)))
    return f"Echo: {first_line}" + (f" | docs: {', '.join(docs)}" if docs else "")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._json({"models": [{"name": m, "size": 1_000_000} for m in MODELS]})
        if self.path.startswith("/api/version"):
            return self._json({"version": "0.0.0-fake"})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = self._body()
        if self.path.startswith("/api/chat"):
            text = _reply(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for piece in re.findall(r"\S+\s*", text) or [text]:
                self.wfile.write((json.dumps({"message": {"content": piece}, "done": False}) + "\n").encode())
            self.wfile.write((json.dumps({"done": True}) + "\n").encode())
            return
        if self.path.startswith("/api/embeddings"):
            return self._json({"embedding": _vector(body.get("prompt", ""))})
        if self.path.startswith("/api/generate"):
            return self._json({"done": True})
        if self.path.startswith("/api/show"):
            return self._json({"modelfile": "", "parameters": "num_ctx 8192", "details": {}})
        self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 11555
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
