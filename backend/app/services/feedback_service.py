"""Answer feedback and model comparisons.

Feedback: a thumbs up/down and an optional "wrong model for this" flag per
assistant message, stored with the model and routing role that produced
it. The routing screen shows the totals per model. Nothing here changes
routing on its own: the numbers are for the user to read and act on.

Comparisons: one prompt sent to several models at once, timed (time to
first token, total time, approximate tokens per second), saved so they
can be reopened and a winner picked later.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator

from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

MAX_MODELS = 4
TEXT_LIMIT = 20000


# ---- feedback --------------------------------------------------------------------

def set_feedback(message_id: str, rating: int | None = None, wrong_model: bool | None = None,
                 note: str | None = None) -> dict:
    with _conn() as conn:
        msg = conn.execute("SELECT id, conversation_id, role, model, route_role FROM messages WHERE id = ?",
                           (message_id,)).fetchone()
        if not msg:
            raise LookupError("No such message.")
        if msg["role"] != "assistant":
            raise ValueError("Only replies can be rated.")
        cur = conn.execute("SELECT * FROM message_feedback WHERE message_id = ?", (message_id,)).fetchone()
        rec = dict(cur) if cur else {"rating": 0, "wrong_model": 0, "note": None}
        if rating is not None:
            rec["rating"] = max(-1, min(1, int(rating)))
        if wrong_model is not None:
            rec["wrong_model"] = 1 if wrong_model else 0
        if note is not None:
            rec["note"] = note.strip()[:500] or None
        conn.execute(
            """INSERT INTO message_feedback (message_id, conversation_id, model, route_role, rating, wrong_model, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(message_id) DO UPDATE SET rating = excluded.rating,
                 wrong_model = excluded.wrong_model, note = excluded.note""",
            (message_id, msg["conversation_id"], msg["model"], msg["route_role"],
             rec["rating"], rec["wrong_model"], rec["note"], time.time()),
        )
    return get_feedback(message_id) or {}


def get_feedback(message_id: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM message_feedback WHERE message_id = ?", (message_id,)).fetchone()
    return dict(r) if r else None


def feedback_for_conversation(conversation_id: str) -> dict[str, dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM message_feedback WHERE conversation_id = ?", (conversation_id,)).fetchall()
    return {r["message_id"]: dict(r) for r in rows}


def clear_feedback(message_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM message_feedback WHERE message_id = ?", (message_id,))


def summary() -> list[dict]:
    """Per model: thumbs up/down, wrong-model flags, and which roles the
    router used it for — the routing screen's feedback table."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT model,
                      SUM(CASE WHEN rating > 0 THEN 1 ELSE 0 END) AS up,
                      SUM(CASE WHEN rating < 0 THEN 1 ELSE 0 END) AS down,
                      SUM(wrong_model) AS wrong_model,
                      GROUP_CONCAT(DISTINCT route_role) AS roles,
                      MAX(created_at) AS last_at
               FROM message_feedback WHERE model IS NOT NULL
               GROUP BY model ORDER BY (up + down + wrong_model) DESC"""
        ).fetchall()
        recent = conn.execute(
            """SELECT f.message_id, f.conversation_id, f.model, f.route_role, f.note, f.created_at, c.title
               FROM message_feedback f LEFT JOIN conversations c ON c.id = f.conversation_id
               WHERE f.wrong_model = 1 ORDER BY f.created_at DESC LIMIT 20"""
        ).fetchall()
    models = []
    for r in rows:
        d = dict(r)
        d["roles"] = [x for x in (d.get("roles") or "").split(",") if x]
        total = (d["up"] or 0) + (d["down"] or 0)
        d["approval"] = round((d["up"] or 0) / total, 2) if total else None
        models.append(d)
    return {"models": models, "wrong_model_recent": [dict(r) for r in recent]}  # type: ignore[return-value]


# ---- comparisons ---------------------------------------------------------------------

def _save_compare(cid: str, prompt: str, results: list[dict]) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO compare_runs (id, prompt, results, winner, created_at) VALUES (?, ?, ?, NULL, ?)",
            (cid, prompt, json.dumps(results), time.time()),
        )


def list_compares(limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM compare_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["results"] = json.loads(d["results"])
        out.append(d)
    return out


def get_compare(cid: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM compare_runs WHERE id = ?", (cid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["results"] = json.loads(d["results"])
    return d


def set_winner(cid: str, model: str | None) -> bool:
    run = get_compare(cid)
    if not run or (model and model not in [x["model"] for x in run["results"]]):
        return False
    with _conn() as conn:
        conn.execute("UPDATE compare_runs SET winner = ? WHERE id = ?", (model, cid))
    return True


def delete_compare(cid: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM compare_runs WHERE id = ?", (cid,))


async def run_compare(prompt: str, models: list[str], system: str | None = None) -> AsyncIterator[dict]:
    """Events: compare_start, token {model, text}, model_done {model, ttft_ms,
    total_ms, tokens, tps, text}, model_error {model, error}, done {id}."""
    from app.services.ollama_client import OllamaClient, ThinkingDelta

    models = list(dict.fromkeys(m for m in models if m))[:MAX_MODELS]
    if len(models) < 2:
        yield {"type": "error", "message": "Pick at least two models."}
        return
    if not prompt.strip():
        yield {"type": "error", "message": "Write a prompt first."}
        return
    cid = uuid.uuid4().hex[:12]
    queue: asyncio.Queue = asyncio.Queue()
    results: dict[str, dict] = {}
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]

    async def one(model: str) -> None:
        t0 = time.perf_counter()
        first = None
        pieces: list[str] = []
        try:
            async for piece in OllamaClient().chat_stream(model, messages):
                if isinstance(piece, ThinkingDelta):
                    continue
                if first is None:
                    first = time.perf_counter()
                pieces.append(str(piece))
                await queue.put({"type": "token", "model": model, "text": str(piece)})
            end = time.perf_counter()
            gen_s = max(end - (first or end), 1e-6)
            text = "".join(pieces)
            res = {"model": model, "text": text[:TEXT_LIMIT], "tokens": len(pieces),
                   "ttft_ms": int(((first or end) - t0) * 1000), "total_ms": int((end - t0) * 1000),
                   "tps": round(len(pieces) / gen_s, 1) if len(pieces) > 1 else None, "error": None}
            results[model] = res
            await queue.put({"type": "model_done", **res})
        except Exception as exc:  # noqa: BLE001 — one model failing must not end the others
            res = {"model": model, "text": "".join(pieces)[:TEXT_LIMIT], "tokens": len(pieces), "ttft_ms": None,
                   "total_ms": int((time.perf_counter() - t0) * 1000), "tps": None, "error": str(exc) or "Failed"}
            results[model] = res
            await queue.put({"type": "model_error", "model": model, "error": res["error"]})

    yield {"type": "compare_start", "id": cid, "models": models}
    tasks = [asyncio.create_task(one(m)) for m in models]

    async def closer() -> None:
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.put(None)

    fin = asyncio.create_task(closer())
    try:
        while True:
            ev = await queue.get()
            if ev is None:
                break
            yield ev
    finally:
        for t in tasks:
            t.cancel()
        fin.cancel()
        if results:
            _save_compare(cid, prompt, [results[m] for m in models if m in results])
    yield {"type": "done", "id": cid}
