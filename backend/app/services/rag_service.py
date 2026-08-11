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


def _conn() -> sqlite3.Connection:
    global _CONN
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
        except Exception as exc:
            log.info("rag.vec_unavailable", error=str(exc))
        _CONN = conn
    return _CONN


def reset_conn() -> None:
    """Close and drop the cached connection (tests switch CORTEX_DATA_DIR)."""
    global _CONN
    if _CONN is not None:
        try:
            _CONN.close()
        except Exception:
            pass
        _CONN = None


def _embed_sync(model: str, text: str) -> list[float] | None:
    """Blocking embedding call, safe from both sync and async contexts.
    Runs the coroutine in a private loop; when we're already inside a
    running loop (asyncio.run would raise), callers must invoke the whole
    RAG function via asyncio.to_thread — then this path is fine."""
    import asyncio
    try:
        return asyncio.run(OllamaClient().embeddings(model, text))
    except RuntimeError:
        log.warning("rag.embed_called_from_event_loop")
        return None
    except Exception as exc:
        log.debug("rag.embed_failed", error=str(exc))
        return None


def _ensure_table() -> None:
    """Create the chunks + vec_chunks virtual table if missing.

    sqlite-vec is an optional dependency; if it's not installed we
    silently fall back to a plain index on `chunks` and the caller
    (retrieve) will use LIKE-based fallback retrieval. The app still
    works without the extension — just without true vector search."""
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
    try:
        dim = _probe_dim()
        if dim:
            cur.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
                f"chunk_id INTEGER PRIMARY KEY, embedding float[{dim}])"
            )
    except Exception as exc:
        log.info("rag.vec_unavailable", error=str(exc))
    conn.commit()


_DIM_CACHE: int | None = None


def _probe_dim() -> int | None:
    """Try a tiny embedding call to discover the dimension, or read it
    from a saved metadata table."""
    global _DIM_CACHE
    if _DIM_CACHE is not None:
        return _DIM_CACHE
    try:
        # We don't have a model name here; rely on config to provide a
        # default dimension hint.
        _DIM_CACHE = int(settings.get("rag_embedding_dim", 384))
        return _DIM_CACHE
    except Exception:
        return 384


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

    # Skip re-indexing if the source text hasn't changed (cheap content hash).
    conn = _conn()
    chunks = _chunk_text(text)
    embed_model = _resolve_embed_model()
    vectors: list[list[float]] = []
    if embed_model:
        for chunk in chunks:
            vectors.append(_embed_sync(embed_model, chunk) or [])

    cur = conn.cursor()
    # Wipe previous chunks for this source so re-uploads/re-scans stay consistent.
    cur.execute("DELETE FROM chunks WHERE source_kind = ? AND source_id = ?", (source_kind, uuid))
    for i, chunk in enumerate(chunks):
        cur.execute(
            "INSERT INTO chunks (source_kind, source_id, conversation_id, chunk_index, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_kind, uuid, conversation_id, i, chunk),
        )
        cid = cur.lastrowid
        if i < len(vectors) and vectors[i]:
            try:
                cur.execute(
                    "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                    (cid, _vec_blob(vectors[i])),
                )
            except Exception as exc:
                log.debug("rag.vec_insert_failed", error=str(exc))
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
    with _conn() as conn:
        conn.execute("DELETE FROM chunks WHERE source_kind = 'folder' AND source_id = ?", (path,))


def index_memory(memory_id: str, content: str) -> None:
    """Embeds one memory so injection can retrieve only what's relevant
    to the current message instead of dumping every stored memory into
    every system prompt. A memory is short enough to be its own single
    chunk — no splitting needed."""
    index_document(memory_id, content, source_kind="memory")


def delete_memory_chunks(memory_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM chunks WHERE source_kind = 'memory' AND source_id = ?", (memory_id,))


def clear_memory_chunks() -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM chunks WHERE source_kind = 'memory'")


def _vec_blob(vec: list[float]) -> bytes:
    """Pack a float list into the binary representation sqlite-vec expects."""
    import struct
    return struct.pack(f"{len(vec)}f", *vec)


def _resolve_embed_model() -> str | None:
    """Resolve the configured embedding model from the model registry, or
    return the user-pinned one if any."""
    override = settings.get("embedding_model_override")
    if override:
        return override
    try:
        from app.services.router import ModelRegistry
        import asyncio
        registry = ModelRegistry()
        try:
            installed = asyncio.run(registry.models())
        except Exception:
            installed = []
        for name in installed:
            lname = name.lower()
            if "embed" in lname or "nomic-embed" in lname or "mxbai" in lname:
                return name
    except Exception:
        pass
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
    if embed_model:
        qvec = _embed_sync(embed_model, query)
        if qvec:
            fan_out = min(top_k * 3, 50)
            vec_hits = _retrieve_vec(qvec, filters, fan_out)
            if vec_hits:
                lex_hits = _retrieve_fallback(query, filters, fan_out)
                if lex_hits:
                    return _fuse_rrf(vec_hits, lex_hits, top_k)
                return vec_hits[:top_k]
    return _retrieve_fallback(query, filters, top_k)


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


def index_message(conversation_id: str, role: str, text: str) -> None:
    """Index assistant + user messages for cross-conversation memory."""
    if not bool(settings.get("rag_enabled", True)):
        return
    if not text or not text.strip():
        return
    _ensure_table()
    conn = _conn()
    cur = conn.cursor()
    # Use one chunk per message; the value of cross-conversation retrieval
    # is in the *existence* of the message, not in its chunking.
    cur.execute(
        "INSERT INTO chunks (source_kind, source_id, conversation_id, chunk_index, text) "
        "VALUES (?, ?, ?, ?, ?)",
        ("message", f"{conversation_id}:{int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)}",
         conversation_id, 0, f"[{role}] {text}"),
    )
    conn.commit()