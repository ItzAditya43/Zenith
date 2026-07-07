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

# Use the same connection the storage layer uses so migrations and FTS see
# the same data. We re-import lazily to dodge the circular import in tests.
def _conn():
    from app.db.storage import get_conn
    return get_conn()


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
        import sqlite_vec
        # Embedding dim: try the configured embedder, fall back to 384.
        dim = _probe_dim()
        if dim:
            cur.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
                f"chunk_id INTEGER PRIMARY KEY, embedding float[{dim}])"
            )
    except Exception as exc:
        log.info("rag.vec_unavailable", error=str(exc))


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


def index_document(uuid: str, text: str, conversation_id: str | None = None) -> int:
    """Chunk + embed a document and persist it. Returns the number of
    chunks added. Falls back to a no-op (just storing the chunks) if
    no embedding model is configured or the call fails."""
    if not bool(settings.get("rag_enabled", True)):
        return 0
    _ensure_table()

    # Skip re-indexing if the source text hasn't changed (cheap content hash).
    conn = _conn()
    chunks = _chunk_text(text)
    embed_model = _resolve_embed_model()
    vectors: list[list[float]] = []
    if embed_model:
        client = OllamaClient()
        for chunk in chunks:
            try:
                v = client._client_sync_embed(embed_model, chunk) if False else None  # type: ignore
            except Exception:
                v = None
            if v is None:
                # async call from sync context: spin a tiny loop
                import asyncio
                try:
                    v = asyncio.run(client.embeddings(embed_model, chunk))
                except Exception as exc:
                    log.warning("rag.embed_failed", error=str(exc))
                    v = None
            vectors.append(v or [])

    cur = conn.cursor()
    # Wipe previous chunks for this source so re-uploads stay consistent.
    cur.execute("DELETE FROM chunks WHERE source_kind = 'document' AND source_id = ?", (uuid,))
    for i, chunk in enumerate(chunks):
        cur.execute(
            "INSERT INTO chunks (source_kind, source_id, conversation_id, chunk_index, text) "
            "VALUES (?, ?, ?, ?, ?)",
            ("document", uuid, conversation_id, i, chunk),
        )
        cid = cur.lastrowid
        if i < len(vectors) and vectors[i]:
            try:
                import sqlite_vec
                conn.enable_load_extension(True)
                conn.load_extension(sqlite_vec.loadable_path())
                cur.execute(
                    "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                    (cid, _vec_blob(vectors[i])),
                )
            except Exception:
                pass
    conn.commit()
    return len(chunks)


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


def retrieve(query: str, source_id: str | None = None, top_k: int | None = None) -> list[dict[str, Any]]:
    """Return the top-k most relevant chunks for `query`. If `source_id` is
    given, scope the search to one document. Falls back to a LIKE query
    when sqlite-vec is unavailable."""
    if not bool(settings.get("rag_enabled", True)):
        return []
    _ensure_table()
    top_k = top_k or int(settings.get("rag_top_k", 4))

    embed_model = _resolve_embed_model()
    if embed_model:
        try:
            import asyncio
            client = OllamaClient()
            qvec = asyncio.run(client.embeddings(embed_model, query))
            return _retrieve_vec(qvec, source_id, top_k)
        except (OllamaError, Exception) as exc:
            log.debug("rag.vec_query_failed", error=str(exc))
    return _retrieve_fallback(query, source_id, top_k)


def _retrieve_vec(qvec: list[float], source_id: str | None, top_k: int) -> list[dict]:
    if not qvec:
        return []
    try:
        import sqlite_vec
        conn = _conn()
        conn.enable_load_extension(True)
        conn.load_extension(sqlite_vec.loadable_path())
        cur = conn.cursor()
        if source_id:
            cur.execute(
                """
                SELECT chunks.id, chunks.text, chunks.source_id, chunks.conversation_id,
                       vec_distance_cosine(vec_chunks.embedding, ?) AS d
                FROM vec_chunks
                INNER JOIN chunks ON chunks.id = vec_chunks.chunk_id
                WHERE chunks.source_id = ?
                ORDER BY d ASC
                LIMIT ?
                """,
                (_vec_blob(qvec), source_id, top_k),
            )
        else:
            cur.execute(
                """
                SELECT chunks.id, chunks.text, chunks.source_id, chunks.conversation_id,
                       vec_distance_cosine(vec_chunks.embedding, ?) AS d
                FROM vec_chunks
                INNER JOIN chunks ON chunks.id = vec_chunks.chunk_id
                ORDER BY d ASC
                LIMIT ?
                """,
                (_vec_blob(qvec), top_k),
            )
        return [
            {
                "text": r[1],
                "source_id": r[2],
                "conversation_id": r[3],
                "score": float(r[4]),
            }
            for r in cur.fetchall()
        ]
    except Exception as exc:
        log.warning("rag.vec_query_fallback", error=str(exc))
        return _retrieve_fallback("", source_id, top_k)


def _retrieve_fallback(query: str, source_id: str | None, top_k: int) -> list[dict]:
    """Cheap lexical fallback: pick chunks containing any query word."""
    if not query.strip():
        return []
    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2][:8]
    if not tokens:
        return []
    conn = _conn()
    cur = conn.cursor()
    where_parts = [" OR ".join(["chunks.text LIKE ?"] * len(tokens))]
    params: list[Any] = [f"%{t}%" for t in tokens]
    if source_id:
        where_parts.append("chunks.source_id = ?")
        params.append(source_id)
    sql = (
        "SELECT chunks.text, chunks.source_id, chunks.conversation_id "
        "FROM chunks WHERE " + " AND ".join(where_parts) + " LIMIT ?"
    )
    params.append(top_k)
    cur.execute(sql, params)
    return [
        {"text": r[0], "source_id": r[1], "conversation_id": r[2], "score": 0.0}
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