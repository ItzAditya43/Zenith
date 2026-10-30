"""Per-turn traces: what one chat/agent/research turn actually did.

usage_events already aggregates tokens and latency; this answers "why did
*this* reply come out like that": which model was routed and why (and how
confident), what was retrieved or fetched into context, every tool call
with its risk and outcome, time-to-first-token, total time, and how it
ended. One row per turn in `turn_traces`, linked to the conversation.

Capture is passive: chat.py's `_sse()` hands every outgoing event to
`observe()`, which feeds the TurnTrace bound to the current context by
`start()`. All three turn kinds emit the same event vocabulary, so none of
the loops need to know tracing exists. Best-effort throughout — a tracing
failure never affects the turn.
"""
from __future__ import annotations

import contextvars
import json
import time
import uuid
from typing import Any

from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

_current: contextvars.ContextVar[TurnTrace | None] = contextvars.ContextVar("zenith_turn_trace", default=None)


class TurnTrace:
    def __init__(self, conversation_id: str, mode: str, user_text: str) -> None:
        self.id = str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.mode = mode
        self.user_text = user_text[:500]
        self.started = time.monotonic()
        self.created_at = time.time()
        self.route: dict[str, Any] = {}
        self.sources: list[dict] = []
        self.tools: dict[str, dict] = {}
        self.tool_order: list[str] = []
        self.tokens = 0
        self.first_token_ms: int | None = None
        self.downgraded_to: str | None = None
        self.status = "running"
        self.error: str | None = None
        self.persisted = False

    def _ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def observe(self, ev: dict[str, Any]) -> None:
        kind = ev.get("type")
        if kind == "route":
            self.route = {k: ev.get(k) for k in ("model", "role", "reason", "confidence")}
        elif kind == "sources":
            self.sources.extend(
                {k: s.get(k) for k in ("kind", "url", "title", "source_id") if s.get(k) is not None}
                for s in ev.get("sources") or [] if isinstance(s, dict)
            )
        elif kind == "tool_call":
            cid = str(ev.get("id"))
            self.tools[cid] = {"tool": ev.get("tool"), "risk": ev.get("risk"), "status": "called",
                               "subagent": bool(ev.get("subagent_of")), "at_ms": self._ms()}
            self.tool_order.append(cid)
        elif kind in ("tool_result", "tool_denied", "tool_pending"):
            call = self.tools.get(str(ev.get("id")))
            if call is not None:
                call["status"] = {"tool_result": "executed", "tool_denied": "denied", "tool_pending": "awaiting"}[kind]
                if kind == "tool_result":
                    result = str(ev.get("result") or "")
                    call["ok"] = not result.startswith("Error")
                    call["ms"] = self._ms() - call["at_ms"]
        elif kind == "token":
            if self.first_token_ms is None:
                self.first_token_ms = self._ms()
            self.tokens += 1
        elif kind == "downgrade":
            self.downgraded_to = ev.get("to")
        elif kind == "done":
            self.finish("ok")
        elif kind == "error":
            self.finish("error", str(ev.get("message") or ""))

    def finish(self, status: str, error: str | None = None) -> None:
        if self.persisted:
            return
        self.persisted = True
        self.status, self.error = status, (error or None)
        try:
            with _conn() as conn:
                conn.execute(
                    """INSERT INTO turn_traces
                       (id, conversation_id, mode, user_text, model, role, reason, confidence,
                        sources, tool_calls, token_count, first_token_ms, total_ms,
                        downgraded_to, status, error, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (self.id, self.conversation_id, self.mode, self.user_text,
                     self.route.get("model"), self.route.get("role"), self.route.get("reason"),
                     self.route.get("confidence"), json.dumps(self.sources),
                     json.dumps([self.tools[c] for c in self.tool_order]), self.tokens,
                     self.first_token_ms, self._ms(), self.downgraded_to, self.status,
                     self.error, self.created_at),
                )
        except Exception as exc:
            log.warning("trace.persist_failed", error=str(exc))


def start(conversation_id: str, mode: str, user_text: str) -> TurnTrace:
    trace = TurnTrace(conversation_id, mode, user_text)
    _current.set(trace)
    return trace


def observe(ev: dict[str, Any]) -> None:
    trace = _current.get()
    if trace is None:
        return
    try:
        trace.observe(ev)
    except Exception as exc:  # never let tracing break a turn
        log.debug("trace.observe_failed", error=str(exc))


def _row(r) -> dict[str, Any]:
    d = dict(r)
    for key in ("sources", "tool_calls"):
        try:
            d[key] = json.loads(d[key] or "[]")
        except (TypeError, json.JSONDecodeError):
            d[key] = []
    return d


def list_traces(conversation_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as conn:
        if conversation_id:
            rows = conn.execute(
                "SELECT * FROM turn_traces WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM turn_traces ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def get_trace(trace_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM turn_traces WHERE id = ?", (trace_id,)).fetchone()
    return _row(r) if r else None


def prune(keep_days: int = 30) -> int:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM turn_traces WHERE created_at < ?", (time.time() - keep_days * 86400,))
    return cur.rowcount
