"""The vector half of hybrid RAG, end to end against real sqlite-vec with a
deterministic fake embedding model. Regression tests for three bugs that
together meant vector search never ran in practice:

1. vec_chunks was created as float[384] regardless of the model, so every
   768-dim (nomic-embed-text) / 1024-dim (mxbai) insert failed silently;
2. embedding from inside the event loop (memory_service.add_memory, called
   from async routes) hit asyncio.run's "running loop" error and was skipped;
3. the documented `rag_embedding_model` setting was never read.
"""
from __future__ import annotations

import hashlib
import math

import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")

DIM = 768


def _fake_vector(text: str, dim: int = DIM) -> list[float]:
    """Bag-of-words hashed into `dim` buckets — texts sharing words land
    close together, which is all retrieval ordering needs."""
    vec = [0.0] * dim
    for word in text.lower().split():
        word = "".join(ch for ch in word if ch.isalnum())
        if word:
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.fixture
def rag(temp_data_dir, monkeypatch):
    from app.core.config import settings
    from app.db.storage import init_db
    from app.services import ollama_client, rag_service

    rag_service.reset_conn()
    init_db()
    calls = {"n": 0, "dim": DIM}

    async def fake_embeddings(self, model, text):
        calls["n"] += 1
        return _fake_vector(text, calls["dim"])

    monkeypatch.setattr(ollama_client.OllamaClient, "embeddings", fake_embeddings)
    settings.update({"rag_embedding_model": "fake-embed", "rag_rerank_enabled": False})
    yield rag_service, calls
    rag_service.reset_conn()


def test_configured_embedding_model_is_used(rag):
    rag_service, _ = rag
    assert rag_service._resolve_embed_model() == "fake-embed"


def test_router_embedding_override_is_honoured(rag):
    from app.core.config import settings

    rag_service, _ = rag
    settings.update({"rag_embedding_model": "", "model_overrides": {"embedding": "role-embed"}})
    assert rag_service._resolve_embed_model() == "role-embed"


def test_768_dim_vectors_are_stored_and_used(rag):
    rag_service, _ = rag
    rag_service.index_document("doc-1", "The quarterly revenue grew because of strong cloud sales.")
    rag_service.index_document("doc-2", "Our cat enjoys sleeping in sunny window spots all afternoon.")
    st = rag_service.status()
    assert st["vector_dim"] == DIM
    assert st["chunks"] == 2 and st["chunks_with_vectors"] == 2
    assert st["mode"] == "hybrid"

    hits = rag_service._retrieve_vec(
        _fake_vector("cloud revenue sales"), rag_service._Filters(None, None, None), 2
    )
    assert hits and hits[0]["source_id"] == "doc-1"


async def test_embedding_from_inside_the_event_loop_works(rag):
    """add_memory is called straight from async code — this used to log
    rag.embed_called_from_event_loop and store no vector."""
    rag_service, calls = rag
    from app.services.memory_service import add_memory

    add_memory("Prefers dark roast coffee in the morning")
    assert calls["n"] >= 1
    assert rag_service.status()["chunks_with_vectors"] >= 1


def test_switching_embedding_dimension_rebuilds_vector_table(rag):
    from app.core.config import settings

    rag_service, calls = rag
    rag_service.index_document("doc-1", "alpha beta gamma")
    assert rag_service.status()["vector_dim"] == DIM

    calls["dim"] = 1024
    settings.update({"rag_embedding_model": "bigger-embed"})
    rag_service.index_document("doc-2", "delta epsilon")
    st = rag_service.status()
    assert st["vector_dim"] == 1024
    assert st["vector_model"] == "bigger-embed"
    assert st["chunks"] == 2 and st["chunks_with_vectors"] == 1  # old vectors dropped, chunk kept

    assert rag_service.reindex_missing_vectors()["embedded"] == 1
    assert rag_service.status()["chunks_missing_vectors"] == 0


def test_legacy_384_table_is_replaced_on_first_real_vector(rag):
    rag_service, _ = rag
    rag_service._ensure_table()
    conn = rag_service._conn()
    conn.execute("CREATE VIRTUAL TABLE vec_chunks USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[384])")
    conn.commit()
    rag_service.index_document("doc-1", "hello vector world")
    st = rag_service.status()
    assert st["vector_dim"] == DIM and st["chunks_with_vectors"] == 1


def test_reindex_embeds_chunks_indexed_without_a_model(rag, monkeypatch):
    from app.core.config import settings

    rag_service, _ = rag
    settings.update({"rag_embedding_model": ""})
    monkeypatch.setattr(rag_service, "_installed_models", lambda: [])  # no embedding model installed
    rag_service.index_document("doc-1", "chunk stored lexical only")
    assert rag_service.status()["mode"] == "lexical"

    settings.update({"rag_embedding_model": "fake-embed"})
    out = rag_service.reindex_missing_vectors()
    assert out == {"embedded": 1, "failed": 0, "error": None}
    assert rag_service.status()["mode"] == "hybrid"


def test_reindex_without_model_reports_why(rag, monkeypatch):
    from app.core.config import settings

    rag_service, _ = rag
    settings.update({"rag_embedding_model": ""})
    monkeypatch.setattr(rag_service, "_installed_models", lambda: [])
    assert "No embedding model" in rag_service.reindex_missing_vectors()["error"]


def test_deleting_sources_removes_their_vectors(rag):
    rag_service, _ = rag
    rag_service.index_document("doc-1", "first document text")
    rag_service.index_folder_file("/notes/a.md", "folder file text", "folder-1")
    rag_service.index_memory("mem-1", "a memory")
    assert rag_service.status()["chunks_with_vectors"] == 3

    rag_service.delete_folder_chunks("/notes/a.md")
    rag_service.delete_memory_chunks("mem-1")
    assert rag_service.delete_source("doc-1", "document") == 1
    st = rag_service.status()
    assert st["chunks"] == 0 and st["chunks_with_vectors"] == 0


def test_reindexing_same_document_does_not_orphan_vectors(rag):
    rag_service, _ = rag
    for _ in range(3):
        rag_service.index_document("doc-1", "same document indexed repeatedly")
    st = rag_service.status()
    assert st["chunks"] == 1 and st["chunks_with_vectors"] == 1


def test_messages_are_embedded_for_cross_conversation_recall(rag):
    rag_service, _ = rag
    rag_service.index_message("conv-1", "user", "How do I configure nginx reverse proxy headers?")
    assert rag_service.status()["chunks_with_vectors"] == 1


def test_status_and_reindex_endpoints(rag, client):
    rag_service, _ = rag
    rag_service.index_document("doc-1", "endpoint check")
    assert client.get("/api/rag/status").json()["mode"] == "hybrid"
    assert client.post("/api/rag/reindex").json()["embedded"] == 0


def test_run_sync_inside_and_outside_a_loop():
    import asyncio

    from app.core.aio import run_sync

    async def answer():
        return 42

    assert run_sync(answer()) == 42

    async def inside():
        return run_sync(answer())

    assert asyncio.run(inside()) == 42

    async def boom():
        raise ValueError("propagates")

    async def inside_boom():
        return run_sync(boom())

    with pytest.raises(ValueError, match="propagates"):
        asyncio.run(inside_boom())


def test_model_switch_reembeds_in_background(rag, monkeypatch):
    import time

    from app.core.config import settings

    rag_service, calls = rag
    rag_service.index_document("doc-1", "alpha beta")
    calls["dim"] = 1024
    settings.update({"rag_embedding_model": "bigger-embed"})
    monkeypatch.delenv("ZENITH_NO_BACKGROUND_REINDEX", raising=False)
    rag_service.index_document("doc-2", "gamma delta")  # triggers rebuild + background re-embed
    for _ in range(50):
        if rag_service.status()["chunks_missing_vectors"] == 0:
            break
        time.sleep(0.05)
    assert rag_service.status()["chunks_missing_vectors"] == 0


def test_shared_connection_survives_concurrent_threads(rag):
    """Index and retrieve from many threads at once (this used to segfault)."""
    import threading

    rag_service, _ = rag
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            for j in range(10):
                rag_service.index_message(f"c{i}", "user", f"message {i}-{j} about topic {j}")
                rag_service.retrieve(f"topic {j}", source_kind="message")
                rag_service.status()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert rag_service.status()["chunks"] == 60
