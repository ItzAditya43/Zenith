"""Conversation compaction with continuity.

Only the last `max_context_messages` messages are sent to the model. Once
messages fall out of that window, a background step folds them into a
structured *conversation state*: goals, decisions, constraints, facts,
files, open questions and next actions. Every item names the messages it
came from, so the user can check it against the source.

The state is tied to the exact message it covers up to (`covered_until`).
If the chat is edited or another branch is active, so that message is no
longer one of the dropped ones, the state is ignored and rebuilt rather
than describing a conversation that no longer exists — except items the
user pinned, which are carried into the rebuild unchanged.

Users can inspect, edit, pin, delete or add items, and regenerate the
whole state (pinned items survive). Recent turns are always sent verbatim;
the state only stands in for what dropped out.
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

BATCH = 6               # update once at least this many new messages have dropped out
MAX_SUMMARY_CHARS = 2400
PER_MESSAGE_CHARS = 1500
MAX_ITEMS_PER_SECTION = 12
MAX_ITEM_CHARS = 400

SECTIONS: list[tuple[str, str]] = [
    ("goals", "Goals"),
    ("decisions", "Decisions"),
    ("constraints", "Constraints"),
    ("facts", "Important facts"),
    ("files", "Files and things being worked on"),
    ("open_questions", "Open questions"),
    ("next_actions", "Next actions"),
]
SECTION_KEYS = [k for k, _ in SECTIONS]

_running: set[str] = set()


def _window() -> int:
    return int(settings.get("max_context_messages", 24))


def _chat(history: list[dict]) -> list[dict]:
    return [m for m in history if m.get("role") in ("user", "assistant")]


def _dropped(history: list[dict]) -> list[dict]:
    chat = _chat(history)
    keep = _window()
    return chat[:-keep] if len(chat) > keep else []


# ---- storage ----------------------------------------------------------------

def _load(conversation_id: str) -> dict | None:
    from app.db.storage import _conn

    with _conn() as conn:
        row = conn.execute(
            "SELECT summary, covered_until, covered_count, state, updated_at, edited_at"
            " FROM conversation_summaries WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["state"] = normalize_state(json.loads(d["state"])) if d.get("state") else None
    except (ValueError, TypeError):
        d["state"] = None
    return d


def _save(conversation_id: str, summary: str, covered_until: str, covered_count: int,
          state: dict | None = None, edited: bool = False) -> None:
    from app.db.storage import _conn

    now = time.time()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO conversation_summaries
                 (conversation_id, summary, covered_until, covered_count, updated_at, state, edited_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(conversation_id) DO UPDATE SET
                 summary = excluded.summary, covered_until = excluded.covered_until,
                 covered_count = excluded.covered_count, updated_at = excluded.updated_at,
                 state = excluded.state,
                 edited_at = COALESCE(excluded.edited_at, conversation_summaries.edited_at)""",
            (conversation_id, summary, covered_until, covered_count, now,
             json.dumps(state) if state is not None else None, now if edited else None),
        )


def clear(conversation_id: str) -> None:
    from app.db.storage import _conn

    with _conn() as conn:
        conn.execute("DELETE FROM conversation_summaries WHERE conversation_id = ?", (conversation_id,))


def _valid(saved: dict | None, dropped: list[dict]) -> bool:
    if not saved or not saved.get("covered_until"):
        return False
    n = int(saved.get("covered_count") or 0)
    return 0 < n <= len(dropped) and dropped[n - 1].get("id") == saved["covered_until"]


# ---- state shape -------------------------------------------------------------

def empty_state() -> dict:
    return {k: [] for k in SECTION_KEYS}


def normalize_state(raw: object) -> dict:
    """Coerce anything (model output, a user edit) into the canonical shape,
    dropping unknown sections and junk items."""
    out = empty_state()
    if not isinstance(raw, dict):
        return out
    for key in SECTION_KEYS:
        items = raw.get(key) or []
        if not isinstance(items, list):
            continue
        for it in items[:MAX_ITEMS_PER_SECTION * 2]:
            if isinstance(it, str):
                it = {"text": it}
            if not isinstance(it, dict):
                continue
            text = str(it.get("text") or "").strip()
            if not text:
                continue
            sources = it.get("sources") or it.get("from") or []
            if not isinstance(sources, list):
                sources = []
            out[key].append({
                "text": text[:MAX_ITEM_CHARS],
                "sources": [str(s) for s in sources if s][:8],
                "pinned": bool(it.get("pinned")),
            })
        # keep pinned first-class: never trim them away
        pinned = [i for i in out[key] if i["pinned"]]
        rest = [i for i in out[key] if not i["pinned"]]
        out[key] = pinned + rest[: max(0, MAX_ITEMS_PER_SECTION - len(pinned))]
    return out


def pinned_only(state: dict | None) -> dict:
    st = normalize_state(state)
    return {k: [i for i in v if i["pinned"]] for k, v in st.items()}


def merge_pinned(new: dict, pinned: dict) -> dict:
    """Put pinned items back, replacing any near-identical model rewrite."""
    out = normalize_state(new)
    for key in SECTION_KEYS:
        keep = pinned.get(key) or []
        texts = {i["text"].lower() for i in keep}
        out[key] = keep + [i for i in out[key] if i["text"].lower() not in texts and not i["pinned"]]
        out[key] = out[key][: max(MAX_ITEMS_PER_SECTION, len(keep))]
    return out


def render_state(state: dict) -> str:
    lines: list[str] = []
    for key, title in SECTIONS:
        items = state.get(key) or []
        if not items:
            continue
        lines.append(f"{title}:")
        lines.extend(f"- {i['text']}" for i in items)
    return "\n".join(lines)[:MAX_SUMMARY_CHARS * 2]


def state_is_empty(state: dict | None) -> bool:
    return not state or not any(state.get(k) for k in SECTION_KEYS)


# ---- what each turn sees ---------------------------------------------------------

def summary_block(conversation_id: str, history: list[dict]) -> str:
    """System-context section for this turn, or "" when there's no valid
    state or nothing has dropped out of the window yet. Pinned items are
    always included once anything has dropped out, even if the rest is
    stale after an edit."""
    if not settings.get("summarize_long_chats", True):
        return ""
    dropped = _dropped(history)
    if not dropped:
        return ""
    saved = _load(conversation_id)
    if not saved:
        return ""
    if not _valid(saved, dropped):
        pins = pinned_only(saved.get("state"))
        if state_is_empty(pins):
            return ""
        return "Things the user pinned about this conversation; treat them as established:\n" + render_state(pins)
    gap = len(dropped) - int(saved["covered_count"])
    note = f" ({gap} more recent older messages aren't summarised yet)" if gap else ""
    body = render_state(saved["state"]) if not state_is_empty(saved.get("state")) else saved["summary"]
    return (
        "State of the earlier part of this conversation. Those messages are no longer shown "
        f"in full{note}; rely on this for what was decided or established:\n" + body
    )


# ---- building ------------------------------------------------------------------

def _render(messages: list[dict], offset: int) -> tuple[str, dict[str, str]]:
    """Messages labelled m1, m2… so the model can cite them; returns the
    text and the label → message-id map."""
    out, refs = [], {}
    for i, m in enumerate(messages, start=offset + 1):
        ref = f"m{i}"
        refs[ref] = m.get("id") or ref
        text = (m.get("content") or "").strip()
        if len(text) > PER_MESSAGE_CHARS:
            text = text[:PER_MESSAGE_CHARS] + " …"
        out.append(f"[{ref}] {m['role'].upper()}: {text}")
    return "\n\n".join(out), refs


def _first_json_object(raw: str) -> dict | None:
    raw = raw.strip()
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


def _map_sources(state: dict, refs: dict[str, str], known_ids: set[str]) -> dict:
    for items in state.values():
        for it in items:
            mapped = []
            for s in it["sources"]:
                s = s.strip().strip("[]")
                if s in refs:
                    mapped.append(refs[s])
                elif s in known_ids:
                    mapped.append(s)
            it["sources"] = list(dict.fromkeys(mapped))
    return state


async def _pick_model() -> str | None:
    from app.services import model_health
    from app.services.router import ModelRegistry, ModelRouter, auto_allowed

    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    for role in ("general", "small_fast"):
        m = router._match_capability(role, installed)  # noqa: SLF001
        if m and not model_health.is_unavailable(m) and auto_allowed(m):
            return m
    return None


_PROMPT = """You keep the working state of a long conversation between a user and an AI assistant, so the assistant stays on track after older messages are dropped.

{previous}Older messages to fold in (each labelled [mN]):
{messages}

Return ONLY a JSON object with these keys, each a list of items:
goals, decisions, constraints, facts, files, open_questions, next_actions.
Each item is {{"text": "<one short sentence>", "sources": ["mN", ...]}} naming the messages it came from.
Keep items that are still true from the current state (keep their sources), update ones that changed, drop ones that were resolved or reversed. At most 8 items per key. No commentary."""


async def update(conversation_id: str, force: bool = False) -> bool:
    """Fold newly dropped messages into the state. Returns True if it wrote
    a new one. Safe to call after every turn: it does nothing until BATCH
    messages have dropped out since the last update. `force` rebuilds from
    scratch (keeping pinned items) even if nothing new dropped out."""
    if conversation_id in _running:
        return False
    if not force and not settings.get("summarize_long_chats", True):
        return False
    from app.db import storage

    history = await asyncio.to_thread(storage.get_messages, conversation_id)
    dropped = _dropped(history)
    if force and not dropped:
        # Regenerating a chat that still fits: compact everything except the
        # last few turns so there's something to look at.
        chat = _chat(history)
        dropped = chat[:-4] if len(chat) > 4 else []
    if not dropped:
        return False
    saved = await asyncio.to_thread(_load, conversation_id)
    pins = pinned_only(saved.get("state") if saved else None)
    if not force and _valid(saved, dropped):
        assert saved is not None
        start = int(saved["covered_count"])
        previous = saved.get("state") or None
        prev_text = saved["summary"]
    else:
        start, previous, prev_text = 0, None, ""
    new = dropped[start:]
    if not force and len(new) < BATCH and start > 0:
        return False
    if not new:
        return False

    _running.add(conversation_id)
    try:
        model = await _pick_model()
        if not model:
            return False
        from app.services.ollama_client import OllamaClient

        messages_text, refs = _render(new, start)
        base = merge_pinned(previous, pins) if previous else pins
        prev_block = ""
        if not state_is_empty(base):
            prev_block = "Current state (JSON):\n" + json.dumps(base, ensure_ascii=False) + "\n\n"
        elif prev_text:
            prev_block = f"Current summary:\n{prev_text}\n\n"
        prompt = _PROMPT.format(previous=prev_block, messages=messages_text)
        raw = (await OllamaClient().chat(model, [{"role": "user", "content": prompt}], format="json")).strip()
        parsed = _first_json_object(raw)
        if parsed is None:
            # A model that ignored the JSON format still gave useful bullets:
            # keep them as facts (cited "[mN]" refs are still picked up).
            lines = [ln.strip().lstrip("-•*").strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return False
            parsed = {"facts": [{"text": re.sub(r"\s*\[(m\d+)\]", "", ln).strip(),
                                 "sources": re.findall(r"\[(m\d+)\]", ln)} for ln in lines]}
        known = {m.get("id") for m in history if m.get("id")}
        state = merge_pinned(_map_sources(normalize_state(parsed), refs, known), pins)
        if state_is_empty(state):
            return False
        text = render_state(state)[:MAX_SUMMARY_CHARS]
        await asyncio.to_thread(_save, conversation_id, text, dropped[-1]["id"], len(dropped), state)
        log.info("summary.updated", conversation_id=conversation_id, covered=len(dropped), model=model)
        return True
    except Exception as exc:
        log.debug("summary.update_failed", error=str(exc))
        return False
    finally:
        _running.discard(conversation_id)


# ---- inspect / edit ------------------------------------------------------------------

def inspect(conversation_id: str) -> dict:
    from app.db import storage

    history = storage.get_messages(conversation_id)
    chat = _chat(history)
    dropped = _dropped(history)
    saved = _load(conversation_id)
    valid = _valid(saved, dropped) if saved else False
    state = (saved or {}).get("state")
    if state is None and saved and saved.get("summary"):
        # A summary written before structured state existed: show it as facts.
        state = normalize_state({"facts": [ln.lstrip("-• ").strip() for ln in saved["summary"].splitlines() if ln.strip()]})
    return {
        "sections": [{"key": k, "title": t} for k, t in SECTIONS],
        "state": state or empty_state(),
        "exists": bool(saved),
        "current": valid,
        "covered_count": int(saved["covered_count"]) if saved else 0,
        "dropped_count": len(dropped),
        "message_count": len(chat),
        "window": _window(),
        "updated_at": saved.get("updated_at") if saved else None,
        "edited_at": saved.get("edited_at") if saved else None,
        "running": conversation_id in _running,
        "enabled": bool(settings.get("summarize_long_chats", True)),
    }


def save_edit(conversation_id: str, state: object) -> dict:
    """Store a user-edited state. Coverage stays as it was (or, for a chat
    with no state yet, covers what has dropped out so far)."""
    from app.db import storage

    st = normalize_state(state)
    saved = _load(conversation_id)
    history = storage.get_messages(conversation_id)
    dropped = _dropped(history)
    if saved and _valid(saved, dropped):
        covered_until, covered_count = saved["covered_until"], int(saved["covered_count"])
    elif dropped:
        covered_until, covered_count = dropped[-1]["id"], len(dropped)
    else:
        chat = _chat(history)
        covered_until = chat[-1]["id"] if chat else "none"
        covered_count = 0
    _save(conversation_id, render_state(st)[:MAX_SUMMARY_CHARS], covered_until, covered_count, st, edited=True)
    return inspect(conversation_id)
