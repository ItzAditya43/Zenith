"""Retrieval-augmented context using sqlite-vec.

Stores per-document chunks with their embeddings in the same SQLite file
the rest of the app uses. No new infrastructure. Falls back to
chunk_for_context() when no embedding model is configured.

This is the highest-leverage feature in the audit: it lets the user ask
"what's on page 300 of this PDF" and get a grounded answer instead of
the silent head+tail truncation we had before.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Any

from app.core.aio import run_sync
from app.core.config import settings
from app.core.logging import get_logger
from app.services.ollama_client import OllamaClient, OllamaError

log = get_logger(__name__)

# One persistent connection for the RAG tables. sqlite-vec (when present)
# must be loaded per-connection, so reusing one avoids re-loading the
# extension on every call. check_same_thread=False because callers hop
# between the event loop and asyncio.to_thread workers; SQLite serializes
# writes internally and we're single-user.
_CONN: sqlite3.Connection | None = None
_VEC_LOADED = False

# One SQLite connection is shared across threads (asyncio.to_thread workers,
# the background re-index). sqlite3 connections aren't safe for concurrent
# use — a background re-index racing a request crashed the process — so every
# database touch holds this lock. Embedding calls (slow, network) never do.
_DB_LOCK = __import__("threading").RLock()


def _locked(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _DB_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _conn() -> sqlite3.Connection:
    global _CONN, _VEC_LOADED
    if _CONN is None:
        from app.core.config import db_path
        conn = sqlite3.connect(str(db_path()), timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            import sqlite_vec
            conn.enable_load_extension(True)
            conn.load_extension(sqlite_vec.loadable_path())
            conn.enable_load_extension(False)
            _VEC_LOADED = True
        except Exception as exc:
            _VEC_LOADED = False
            log.info("rag.vec_unavailable", error=str(exc))
        _CONN = conn
    return _CONN


@_locked
def reset_conn() -> None:
    """Close and drop the cached connection (tests switch ZENITH_DATA_DIR)."""
    global _CONN
    if _CONN is not None:
        try:
            _CONN.close()
        except Exception:
            pass
        _CONN = None


def _embed_sync(model: str, text: str) -> list[float] | None:
    """Blocking embedding call, safe from both sync and async contexts
    (see app/core/aio.py — this used to return None whenever it was
    reached from inside the event loop)."""
    try:
        return run_sync(OllamaClient().embeddings(model, text))
    except Exception as exc:
        log.warning("rag.embed_failed", model=model, error=str(exc) or type(exc).__name__)
        return None


@_locked
def _ensure_table() -> None:
    """Create the chunks table (and the small rag_meta table) if missing.

    The vector table is created lazily by _ensure_vec_table() once the
    first embedding comes back — its width has to match the embedding
    model's real dimension (384 / 768 / 1024 / ...), which isn't known
    until then. sqlite-vec is optional; without it retrieval is lexical."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind TEXT NOT NULL,  -- 'document' | 'message'
            source_id TEXT NOT NULL,    -- file uuid or conversation id
            conversation_id TEXT,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at REAL DEFAULT (strftime('%s','now'))
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_kind, source_id)")
    cur.execute("CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()


@_locked
def _meta_get(key: str) -> str | None:
    row = _conn().execute("SELECT value FROM rag_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _meta_set(cur: sqlite3.Cursor, key: str, value: str) -> None:
    cur.execute("INSERT INTO rag_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


@_locked
def _vec_table_dim() -> int | None:
    """Width of the existing vec_chunks table, read from its DDL (covers
    databases created before rag_meta existed, which were always 384)."""
    row = _conn().execute("SELECT sql FROM sqlite_master WHERE name = 'vec_chunks'").fetchone()
    if not row or not row[0]:
        return None
    m = re.search(r"float\[(\d+)\]", row[0])
    return int(m.group(1)) if m else None


@_locked
def _ensure_vec_table(dim: int, model: str) -> bool:
    """Make sure vec_chunks exists with width `dim` for `model`. Switching
    embedding model (or dimension) drops the old vectors — vectors from two
    different models aren't comparable — and logs it; the chunks stay, so
    lexical recall keeps working and reindex_missing_vectors() re-embeds."""
    if not _VEC_LOADED:
        return False
    conn = _conn()
    existing = _vec_table_dim()
    stored_model = _meta_get("vec_model")
    if existing == dim and stored_model in (model, None):
        if stored_model is None:
            cur = conn.cursor()
            _meta_set(cur, "vec_model", model)
            _meta_set(cur, "vec_dim", str(dim))
            conn.commit()
        return True
    cur = conn.cursor()
    if existing is not None:
        log.warning("rag.vec_table_rebuilt", old_dim=existing, new_dim=dim,
                    old_model=stored_model, new_model=model)
        cur.execute("DROP TABLE vec_chunks")
    cur.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{int(dim)}])")
    _meta_set(cur, "vec_model", model)
    _meta_set(cur, "vec_dim", str(dim))
    conn.commit()
    if existing is not None:
        _schedule_reindex()
    return True


_reindex_lock = __import__("threading").Lock()


def _schedule_reindex() -> None:
    """After an embedding-model switch, re-embed the dropped chunks in the
    background instead of waiting for the user to press a button."""
    import os
    import threading

    if os.environ.get("ZENITH_NO_BACKGROUND_REINDEX"):
        return

    def run() -> None:
        if not _reindex_lock.acquire(blocking=False):
            return
        try:
            reindex_missing_vectors()
        except Exception as exc:
            log.warning("rag.auto_reindex_failed", error=str(exc))
        finally:
            _reindex_lock.release()

    threading.Thread(target=run, name="zenith-reindex", daemon=True).start()


def _vectors_usable_for(model: str) -> bool:
    return _VEC_LOADED and _vec_table_dim() is not None and _meta_get("vec_model") in (model, None)


def _insert_vector(cur: sqlite3.Cursor, chunk_id: int, vec: list[float], model: str) -> bool:
    if not vec or not _ensure_vec_table(len(vec), model):
        return False
    try:
        cur.execute("INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)", (chunk_id, _vec_blob(vec)))
        return True
    except Exception as exc:
        log.warning("rag.vec_insert_failed", error=str(exc))
        return False


@_locked
def _delete_chunks(where: str, params: tuple) -> int:
    """Delete chunks matching `where` *and* their vectors (the old
    per-kind deletes left orphaned vec_chunks rows behind)."""
    _ensure_table()
    conn = _conn()
    cur = conn.cursor()
    ids = [r[0] for r in cur.execute(f"SELECT id FROM chunks WHERE {where}", params).fetchall()]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    if _vec_table_dim() is not None:
        try:
            cur.execute(f"DELETE FROM vec_chunks WHERE chunk_id IN ({placeholders})", ids)
        except Exception as exc:
            log.warning("rag.vec_delete_failed", error=str(exc))
    cur.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", ids)
    conn.commit()
    return len(ids)


def _chunk_text(text: str) -> list[str]:
    size = int(settings.get("rag_chunk_chars", 1200))
    overlap = int(settings.get("rag_chunk_overlap", 150))
    if overlap >= size:
        overlap = max(0, size // 4)
    if len(text) <= size:
        return [text]
    out = []
    i = 0
    while i < len(text):
        out.append(text[i : i + size])
        i += size - overlap
    return out


def _hash_source(source_kind: str, source_id: str) -> str:
    return hashlib.sha1(f"{source_kind}::{source_id}".encode()).hexdigest()


def index_document(uuid: str, text: str, conversation_id: str | None = None,
                    source_kind: str = "document") -> int:
    """Chunk + embed a document and persist it. Returns the number of
    chunks added. Falls back to a no-op (just storing the chunks) if
    no embedding model is configured or the call fails. `source_kind`
    defaults to "document" (uploaded attachments); folder_service passes
    "folder" so watched-folder content and chat uploads stay in
    separate, independently-queryable buckets."""
    if not bool(settings.get("rag_enabled", True)):
        return 0
    _ensure_table()

    chunks = _chunk_text(text)
    embed_model = _resolve_embed_model()
    vectors: list[list[float]] = []
    if embed_model:
        for chunk in chunks:
            vectors.append(_embed_sync(embed_model, chunk) or [])

    with _DB_LOCK:
        # Wipe previous chunks for this source so re-uploads/re-scans stay consistent.
        _delete_chunks("source_kind = ? AND source_id = ?", (source_kind, uuid))
        conn = _conn()
        cur = conn.cursor()
        for i, chunk in enumerate(chunks):
            cur.execute(
                "INSERT INTO chunks (source_kind, source_id, conversation_id, chunk_index, text) "
                "VALUES (?, ?, ?, ?, ?)",
                (source_kind, uuid, conversation_id, i, chunk),
            )
            cid = cur.lastrowid
            if embed_model and cid is not None and i < len(vectors) and vectors[i]:
                _insert_vector(cur, cid, vectors[i], embed_model)
        conn.commit()
    return len(chunks)


def index_folder_file(path: str, text: str, folder_id: str) -> int:
    """Chunk + embed one file from a watched folder. `path` is the
    absolute filesystem path — stable across re-scans, so re-indexing a
    changed file cleanly replaces its old chunks rather than duplicating
    them (same DELETE-then-INSERT as index_document)."""
    return index_document(path, text, conversation_id=None, source_kind="folder")


def delete_folder_chunks(path: str) -> None:
    """Removes a file's chunks — called when a watched file disappears
    or its folder is removed, so stale content doesn't linger in recall."""
    _delete_chunks("source_kind = 'folder' AND source_id = ?", (path,))


def index_memory(memory_id: str, content: str) -> None:
    """Embeds one memory so injection can retrieve only what's relevant
    to the current message instead of dumping every stored memory into
    every system prompt. A memory is short enough to be its own single
    chunk — no splitting needed."""
    index_document(memory_id, content, source_kind="memory")


def delete_memory_chunks(memory_id: str) -> None:
    _delete_chunks("source_kind = 'memory' AND source_id = ?", (memory_id,))


def clear_memory_chunks() -> None:
    _delete_chunks("source_kind = 'memory'", ())


def _vec_blob(vec: list[float]) -> bytes:
    """Pack a float list into the binary representation sqlite-vec expects."""
    import struct
    return struct.pack(f"{len(vec)}f", *vec)


def _installed_models() -> list[str]:
    from app.services.router import ModelRegistry

    try:
        return run_sync(ModelRegistry().models())
    except Exception as exc:
        log.warning("rag.model_list_failed", error=str(exc))
        return []


def _resolve_embed_model() -> str | None:
    """Embedding model, in priority order: the documented
    `rag_embedding_model` setting, the router's `embedding` role override,
    the pre-v0.1 `embedding_model_override` key, then the first installed
    model whose name looks embedding-capable."""
    for pinned in (
        settings.get("rag_embedding_model"),
        (settings.get("model_overrides") or {}).get("embedding"),
        settings.get("embedding_model_override"),
    ):
        if pinned:
            return str(pinned)
    for name in _installed_models():
        lname = name.lower()
        if "embed" in lname or "nomic-embed" in lname or "mxbai" in lname:
            return name
    return None


_RRF_K = 60  # standard constant from the original RRF paper


def retrieve(
    query: str,
    source_id: str | None = None,
    top_k: int | None = None,
    source_kind: str | None = None,
    exclude_conversation_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return the top-k most relevant chunks for `query`. `source_id`
    scopes to one document; `source_kind`/`exclude_conversation_id` power
    cross-conversation recall (past-message chunks, minus the current
    conversation). Blocking — call via asyncio.to_thread from async code.

    When sqlite-vec + an embedding model are both available, this runs
    vector search and the lexical LIKE search in parallel and fuses their
    rankings with Reciprocal Rank Fusion (RRF) — exact-keyword matches
    (function names, error codes) that embeddings alone sometimes bury
    get a chance to surface. In that fused case `score` is the RRF score
    (higher is better); it is NOT a cosine distance and the two are not
    comparable across calls. Falls back to lexical-only when sqlite-vec
    is unavailable, no embedding model is configured, or vector search
    raises/returns nothing — in all of those cases `score` keeps its old
    meaning (LIKE match count) unchanged."""
    if not bool(settings.get("rag_enabled", True)):
        return []
    _ensure_table()
    top_k = top_k or int(settings.get("rag_top_k", 4))
    filters = _Filters(source_id, source_kind, exclude_conversation_id)

    embed_model = _resolve_embed_model()
    if embed_model and _vectors_usable_for(embed_model):
        qvec = _embed_sync(embed_model, query)
        if qvec:
            fan_out = min(top_k * 3, 50)
            vec_hits = _retrieve_vec(qvec, filters, fan_out)
            if vec_hits:
                lex_hits = _retrieve_fallback(query, filters, fan_out)
                if lex_hits:
                    fused = _fuse_rrf(vec_hits, lex_hits, fan_out)
                    return _maybe_rerank(query, fused, top_k)
                return _maybe_rerank(query, vec_hits, top_k)
    fan_out = min(top_k * 3, 50) if bool(settings.get("rag_rerank_enabled", False)) else top_k
    return _maybe_rerank(query, _retrieve_fallback(query, filters, fan_out), top_k)


def _fuse_rrf(vec_hits: list[dict], lex_hits: list[dict], top_k: int) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion: combine two ranked lists into one, scoring
    by 1/(k + rank) summed across lists so a chunk ranked highly by either
    signal (or both) rises to the top. Fuses on chunk `id`, not text —
    two chunks can share identical text."""
    scores: dict[int, float] = {}
    rows: dict[int, dict] = {}
    for hits in (vec_hits, lex_hits):
        for rank, hit in enumerate(hits, start=1):
            cid = hit["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
            rows.setdefault(cid, hit)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    out = []
    for cid, score in ranked:
        row = dict(rows[cid])
        row["score"] = score
        out.append(row)
    return out


_RERANK_POOL_CAP_DEFAULT = 15


def _maybe_rerank(query: str, candidates: list[dict], top_k: int) -> list[dict[str, Any]]:
    """Optional second-pass rerank of the fused/vector/lexical candidates.
    Only runs when `rag_rerank_enabled` is set AND there are more
    candidates than we actually need to return — reranking a list you're
    already returning in full is pure latency for no benefit. On any
    failure (Ollama unreachable, model output unparseable, timeout) this
    silently falls back to the pre-rerank order, same as `_retrieve_vec`
    falls back to lexical-only on error."""
    if not candidates:
        return candidates[:top_k]
    if not bool(settings.get("rag_rerank_enabled", False)):
        return candidates[:top_k]
    if len(candidates) <= top_k:
        return candidates[:top_k]
    pool_cap = int(settings.get("rag_rerank_pool", _RERANK_POOL_CAP_DEFAULT))
    pool = candidates[:pool_cap]
    try:
        reranked = _rerank_sync(query, pool)
    except Exception as exc:
        log.warning("rag.rerank_failed", error=str(exc))
        reranked = None
    if not reranked:
        return candidates[:top_k]
    # Anything beyond the reranked pool (rare — only when candidates >
    # pool_cap) keeps its original fused order, appended after.
    return (reranked + candidates[len(pool):])[:top_k]


def _resolve_rerank_model() -> str | None:
    """Pick a general chat model to score relevance with. Prefers a
    user-pinned override, else the first installed non-embedding model —
    unlike _resolve_embed_model, we want a chat-capable model here, not an
    embedding one."""
    override = settings.get("rag_rerank_model")
    if override:
        return override
    for name in _installed_models():
        lname = name.lower()
        if "embed" in lname or "nomic-embed" in lname or "mxbai" in lname:
            continue
        return name
    return None


def _build_rerank_prompt(query: str, candidates: list[dict]) -> str:
    lines = [
        "Rate how relevant each numbered passage is to the query, on a "
        "0-100 scale (100 = directly answers the query, 0 = irrelevant).",
        f"Query: {query}",
        "Passages:",
    ]
    for i, cand in enumerate(candidates, start=1):
        snippet = (cand.get("text") or "")[:600].replace("\n", " ")
        lines.append(f"[{i}] {snippet}")
    lines.append(
        "Respond with ONLY one line per passage in the exact format "
        "'N: score' (e.g. '1: 87'), one per line, no other text, no explanation."
    )
    return "\n".join(lines)


def _parse_rerank_scores(reply: str, n: int) -> list[float] | None:
    scores: list[float | None] = [None] * n
    for m in re.finditer(r"(?m)^\s*\[?(\d+)\]?\s*[:\-.]\s*(\d{1,3})\b", reply or ""):
        idx = int(m.group(1)) - 1
        if 0 <= idx < n:
            scores[idx] = float(min(100, max(0, int(m.group(2)))))
    if all(s is None for s in scores):
        return None
    return [s if s is not None else 0.0 for s in scores]


def _rerank_sync(query: str, candidates: list[dict]) -> list[dict] | None:
    """Blocking, single batched Ollama chat call that scores all pooled
    candidates in one round trip (cheaper than one call per candidate —
    this is a latency-sensitive path). Mirrors `_embed_sync`'s
    run-a-private-loop pattern; safe from both sync and async contexts."""
    model = _resolve_rerank_model()
    if not model:
        return None
    prompt = _build_rerank_prompt(query, candidates)
    timeout = float(settings.get("rag_rerank_timeout_seconds", 12))
    import asyncio

    async def _call() -> str:
        return await asyncio.wait_for(
            OllamaClient().chat(model, [{"role": "user", "content": prompt}],
                                 options={"temperature": 0}),
            timeout=timeout,
        )

    try:
        reply = run_sync(_call())
    except (TimeoutError, OllamaError) as exc:
        log.warning("rag.rerank_call_failed", error=str(exc))
        return None
    except Exception as exc:
        log.warning("rag.rerank_call_failed", error=str(exc))
        return None

    scores = _parse_rerank_scores(reply, len(candidates))
    if scores is None:
        log.warning("rag.rerank_unparseable_reply")
        return None
    scored = sorted(zip(candidates, scores, strict=False), key=lambda cs: cs[1], reverse=True)
    out = []
    for cand, score in scored:
        row = dict(cand)
        row["score"] = score
        row["rerank_score"] = score
        out.append(row)
    return out


class _Filters:
    """Shared WHERE-clause builder for the vec and lexical paths."""

    def __init__(self, source_id: str | None, source_kind: str | None,
                 exclude_conversation_id: str | None) -> None:
        self.clauses: list[str] = []
        self.params: list[Any] = []
        if source_id:
            self.clauses.append("chunks.source_id = ?")
            self.params.append(source_id)
        if source_kind:
            self.clauses.append("chunks.source_kind = ?")
            self.params.append(source_kind)
        if exclude_conversation_id:
            self.clauses.append(
                "(chunks.conversation_id IS NULL OR chunks.conversation_id != ?)"
            )
            self.params.append(exclude_conversation_id)


@_locked
def _retrieve_vec(qvec: list[float], filters: _Filters, top_k: int) -> list[dict]:
    if not qvec:
        return []
    where = (" AND " + " AND ".join(filters.clauses)) if filters.clauses else ""
    try:
        cur = _conn().cursor()
        cur.execute(
            f"""
            SELECT chunks.id, chunks.text, chunks.source_id, chunks.conversation_id,
                   vec_distance_cosine(vec_chunks.embedding, ?) AS d, chunks.chunk_index
            FROM vec_chunks
            INNER JOIN chunks ON chunks.id = vec_chunks.chunk_id
            WHERE 1=1{where}
            ORDER BY d ASC
            LIMIT ?
            """,
            (_vec_blob(qvec), *filters.params, top_k),
        )
        return [
            {"id": r[0], "text": r[1], "source_id": r[2], "conversation_id": r[3],
             "score": float(r[4]), "chunk_index": r[5]}
            for r in cur.fetchall()
        ]
    except Exception as exc:
        log.warning("rag.vec_query_fallback", error=str(exc))
        return []


@_locked
def _retrieve_fallback(query: str, filters: _Filters, top_k: int) -> list[dict]:
    """Cheap lexical fallback: rank chunks by how many query words they
    contain (recent first as tiebreak)."""
    if not query.strip():
        return []
    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2][:8]
    if not tokens:
        return []
    like_score = " + ".join(["(chunks.text LIKE ?)"] * len(tokens))
    params: list[Any] = [f"%{t}%" for t in tokens]
    where = (" AND " + " AND ".join(filters.clauses)) if filters.clauses else ""
    sql = (
        f"SELECT * FROM ("
        f"  SELECT chunks.id, chunks.text, chunks.source_id, chunks.conversation_id,"
        f"         ({like_score}) AS s, chunks.created_at AS ca, chunks.chunk_index"
        f"  FROM chunks WHERE 1=1{where}"
        f") WHERE s > 0 ORDER BY s DESC, ca DESC LIMIT ?"
    )
    cur = _conn().cursor()
    cur.execute(sql, (*params, *filters.params, top_k))
    return [
        {"id": r[0], "text": r[1], "source_id": r[2], "conversation_id": r[3],
         "score": float(r[4]), "chunk_index": r[6]}
        for r in cur.fetchall()
    ]


@_locked
def list_sources() -> list[dict[str, Any]]:
    """Group the chunks table by (source_id, source_kind) so the user can
    see, at a glance, everything currently contributing to RAG recall:
    uploaded documents, watched-folder files, cross-conversation message
    history, and stored memories. Read-only — does not touch retrieve()
    or any of its helpers.

    Labeling is best-effort per kind:
      - "document": look up the attachment's original filename via
        attachments.get(source_id); falls back to the raw id if the
        attachment record is gone (e.g. cleaned up after the chat that
        uploaded it was deleted, but its chunks weren't).
      - "folder": source_id is already the absolute file path (see
        index_folder_file) — use its basename as the label, full path
        as a secondary detail.
      - "message": source_id is "{conversation_id}:{hash}"; look up the
        conversation's title via storage.get_conversation for the label.
      - "memory": source_id is the memory id; no separate lookup table
        is read here (memory_service is out of scope for this function),
        so the label is just the id.
      - anything else: label falls back to the raw source_id.
    """
    _ensure_table()
    cur = _conn().cursor()
    cur.execute(
        """
        SELECT source_kind, source_id,
               COUNT(*) AS chunk_count,
               MIN(created_at) AS first_indexed,
               MAX(created_at) AS last_indexed,
               MAX(conversation_id) AS conversation_id
        FROM chunks
        GROUP BY source_kind, source_id
        ORDER BY last_indexed DESC
        """
    )
    rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for source_kind, source_id, chunk_count, first_indexed, last_indexed, conversation_id in rows:
        label = source_id
        detail = None
        try:
            if source_kind == "document":
                from app.services import attachments as att_service
                att = att_service.get(source_id)
                if att is not None:
                    label = att.filename
            elif source_kind == "folder":
                from pathlib import Path
                label = Path(source_id).name or source_id
                detail = source_id
            elif source_kind == "message":
                if conversation_id:
                    from app.db import storage
                    convo = storage.get_conversation(conversation_id)
                    if convo:
                        label = convo.get("title") or f"Conversation {conversation_id}"
                    else:
                        label = f"Conversation {conversation_id}"
        except Exception as exc:
            log.debug("rag.list_sources_label_failed", source_kind=source_kind,
                       source_id=source_id, error=str(exc))
        out.append({
            "source_id": source_id,
            "source_kind": source_kind,
            "label": label,
            "detail": detail,
            "chunk_count": chunk_count,
            "conversation_id": conversation_id,
            "first_indexed": first_indexed,
            "last_indexed": last_indexed,
        })
    return out


@_locked
def delete_source(source_id: str, source_kind: str | None = None) -> int:
    """Delete all chunks for a source (and their vec_chunks rows), same
    cleanup pattern as delete_folder_chunks/delete_memory_chunks. Returns
    the number of chunk rows deleted. `source_kind` narrows the match;
    omit it only if the caller is certain source_id can't collide across
    kinds (in this codebase source_ids are UUIDs or absolute paths, so in
    practice they don't, but the API layer requires the param anyway)."""
    if source_kind:
        return _delete_chunks("source_kind = ? AND source_id = ?", (source_kind, source_id))
    return _delete_chunks("source_id = ?", (source_id,))


def index_message(conversation_id: str, role: str, text: str) -> None:
    """Index assistant + user messages for cross-conversation memory."""
    if not bool(settings.get("rag_enabled", True)):
        return
    if not text or not text.strip():
        return
    _ensure_table()
    # Use one chunk per message; the value of cross-conversation retrieval
    # is in the *existence* of the message, not in its chunking.
    chunk_text = f"[{role}] {text}"
    embed_model = _resolve_embed_model()
    vec = (_embed_sync(embed_model, chunk_text[: int(settings.get("rag_chunk_chars", 1200))])
           if embed_model else None)
    with _DB_LOCK:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chunks (source_kind, source_id, conversation_id, chunk_index, text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("message", f"{conversation_id}:{int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)}",
             conversation_id, 0, chunk_text),
        )
        cid = cur.lastrowid
        if embed_model and vec and cid is not None:
            _insert_vector(cur, cid, vec, embed_model)
        conn.commit()


@_locked
def _chunks_missing_vectors(limit: int | None = None) -> list[tuple[int, str]]:
    sql = "SELECT id, text FROM chunks"
    if _vec_table_dim() is not None:
        sql += " WHERE id NOT IN (SELECT chunk_id FROM vec_chunks)"
    sql += " ORDER BY id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return _conn().execute(sql).fetchall()


@_locked
def status() -> dict[str, Any]:
    """What RAG is actually doing — surfaced in the RAG source manager and
    /api/health so "hybrid search" can't silently be lexical-only again."""
    _ensure_table()
    model = _resolve_embed_model()
    total = _conn().execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    vectors = 0
    if _vec_table_dim() is not None:
        vectors = _conn().execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    return {
        "embedding_model": model,
        "vector_extension": _VEC_LOADED,
        "vector_model": _meta_get("vec_model"),
        "vector_dim": _vec_table_dim(),
        "chunks": total,
        "chunks_with_vectors": vectors,
        "chunks_missing_vectors": max(0, total - vectors),
        "mode": "hybrid" if model and _VEC_LOADED and vectors else "lexical",
    }


def reindex_missing_vectors(limit: int | None = None) -> dict[str, Any]:
    """Embed every chunk that has no vector yet — chunks indexed while no
    embedding model was installed, before the dimension fix, or after an
    embedding-model switch. Blocking; call via asyncio.to_thread."""
    _ensure_table()
    model = _resolve_embed_model()
    if not model:
        return {"embedded": 0, "failed": 0, "error": "No embedding model installed (e.g. `ollama pull nomic-embed-text`)."}
    if not _VEC_LOADED:
        return {"embedded": 0, "failed": 0, "error": "sqlite-vec isn't available, so vectors can't be stored."}
    embedded = failed = 0
    for chunk_id, text in _chunks_missing_vectors(limit):
        vec = _embed_sync(model, text)  # outside the lock: requests keep flowing
        with _DB_LOCK:
            conn = _conn()
            ok = bool(vec) and _insert_vector(conn.cursor(), chunk_id, vec or [], model)
            conn.commit()
        embedded += ok
        failed += not ok
    log.info("rag.reindex_done", model=model, embedded=embedded, failed=failed)
    return {"embedded": embedded, "failed": failed, "error": None}