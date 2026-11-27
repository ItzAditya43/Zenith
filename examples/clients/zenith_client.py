"""A small Zenith API client using only the Python standard library.

    from zenith_client import Zenith
    z = Zenith("http://127.0.0.1:8420", key="zk_...")   # key from Settings → Data → API keys
    cid = z.new_chat("From a script")["id"]
    for piece in z.chat(cid, "Summarise today's news in three bullets"):
        print(piece, end="", flush=True)

Covers chat streaming, conversations, files, models and notifications
(events). Everything else is in the OpenAPI schema at /openapi.json.
"""
from __future__ import annotations

import json
import mimetypes
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path


class ZenithError(RuntimeError):
    pass


class Zenith:
    def __init__(self, base_url: str = "http://127.0.0.1:8420", key: str | None = None, timeout: float = 600):
        self.base = base_url.rstrip("/")
        self.key = key
        self.timeout = timeout

    # -- plumbing ---------------------------------------------------------
    def _req(self, method: str, path: str, body: bytes | None = None, ctype: str | None = None):
        req = urllib.request.Request(self.base + path, data=body, method=method)
        if self.key:
            req.add_header("Authorization", f"Bearer {self.key}")
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="ignore")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            raise ZenithError(f"{exc.code}: {detail}") from None

    def _json(self, method: str, path: str, payload: dict | None = None):
        body = json.dumps(payload).encode() if payload is not None else None
        with self._req(method, path, body, "application/json" if body else None) as r:
            return json.loads(r.read() or b"null")

    # -- API --------------------------------------------------------------
    def version(self) -> dict:
        return self._json("GET", "/api/version")

    def models(self) -> list[dict]:
        return self._json("GET", "/api/models")

    def conversations(self) -> list[dict]:
        return self._json("GET", "/api/conversations")

    def new_chat(self, title: str = "New chat") -> dict:
        return self._json("POST", "/api/conversations", {"title": title})

    def messages(self, conversation_id: str) -> list[dict]:
        return self._json("GET", f"/api/conversations/{conversation_id}/messages")

    def upload(self, path: str | Path, conversation_id: str | None = None) -> dict:
        """Attach a file; pass the returned id in chat(..., attachments=[id])."""
        path = Path(path)
        boundary = uuid.uuid4().hex
        parts = []
        if conversation_id:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="conversation_id"\r\n\r\n{conversation_id}\r\n'.encode())
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
                     + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        with self._req("POST", "/api/upload", b"".join(parts), f"multipart/form-data; boundary={boundary}") as r:
            return json.loads(r.read())

    def chat_events(self, conversation_id: str, message: str, attachments: list[str] | None = None,
                    model: str | None = None, **flags) -> Iterator[dict]:
        """Every streamed event: route, sources, token, done, error…"""
        payload = {"conversation_id": conversation_id, "message": message, "attachment_ids": attachments or [],
                   "model_override": model, **flags}
        with self._req("POST", "/api/chat", json.dumps(payload).encode(), "application/json") as r:
            for raw in r:
                line = raw.decode(errors="ignore").strip()
                if line.startswith("data:"):
                    ev = json.loads(line[5:])
                    yield ev
                    if ev.get("type") in ("done", "error"):
                        return

    def chat(self, conversation_id: str, message: str, **kw) -> Iterator[str]:
        """Just the reply text, as it streams."""
        for ev in self.chat_events(conversation_id, message, **kw):
            if ev.get("type") == "token":
                yield ev.get("text", "")
            elif ev.get("type") == "error":
                raise ZenithError(ev.get("message", "chat failed"))

    def notifications(self, since: float | None = None) -> list[dict]:
        """What happened (finished schedules and background tasks, digests…)."""
        q = f"?since={since}" if since else ""
        return self._json("GET", f"/api/notifications{q}")["items"]


if __name__ == "__main__":
    import os
    import sys

    z = Zenith(os.environ.get("ZENITH_URL", "http://127.0.0.1:8420"), os.environ.get("ZENITH_KEY"))
    print("API", z.version())
    cid = z.new_chat("Client example")["id"]
    for piece in z.chat(cid, " ".join(sys.argv[1:]) or "Say hello in five words."):
        print(piece, end="", flush=True)
    print()
