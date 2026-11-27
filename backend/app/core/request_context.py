"""Request IDs and user-facing error IDs.

Every HTTP request gets an ID (the caller's X-Request-ID if it sent a sane
one, otherwise a new one). It's returned in the X-Request-ID response
header and attached to every log line written while handling the request.

An unhandled exception is logged once, with its traceback and that ID,
and the client gets {"detail": ..., "error_id": <ID>} instead of a bare
"Internal Server Error". The UI shows the ID, so a bug report can point
at the exact log lines (see the diagnostic bundle).
"""
from __future__ import annotations

import re
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_var

log = get_logger(__name__)
_SANE = re.compile(r"^[A-Za-z0-9._-]{6,64}$")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class RequestContext:
    """Pure ASGI middleware (keeps streaming responses untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _SANE.match(incoming) else new_id()
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id_var.set(rid)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", rid.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or new_id()
    log.error("request.unhandled_error", request_id=rid, path=request.url.path, method=request.method,
              error=f"{type(exc).__name__}: {exc}"[:500], exc_info=exc)
    return JSONResponse(
        {"detail": "Something went wrong inside Zenith. The error ID is in the log and the diagnostic bundle.",
         "error_id": rid},
        status_code=500, headers={"X-Request-ID": rid},
    )
