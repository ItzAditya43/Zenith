"""Unit tests for rag_service's Reciprocal Rank Fusion logic. No model or
sqlite-vec needed — this only exercises the pure fusion function."""
from app.services import rag_service


def test_fuse_rrf_prefers_items_ranked_high_in_both_lists():
    vec_hits = [
        {"id": 1, "text": "a", "source_id": "s", "conversation_id": None, "score": 0.1, "chunk_index": 0},
        {"id": 2, "text": "b", "source_id": "s", "conversation_id": None, "score": 0.2, "chunk_index": 1},
        {"id": 3, "text": "c", "source_id": "s", "conversation_id": None, "score": 0.3, "chunk_index": 2},
    ]
    lex_hits = [
        {"id": 3, "text": "c", "source_id": "s", "conversation_id": None, "score": 2.0, "chunk_index": 2},
        {"id": 2, "text": "b", "source_id": "s", "conversation_id": None, "score": 1.0, "chunk_index": 1},
    ]
    fused = rag_service._fuse_rrf(vec_hits, lex_hits, top_k=3)
    ids = [row["id"] for row in fused]
    # ids 2 and 3 each appear in both lists (so their RRF scores sum two
    # contributions) and both outrank id 1, which only appears once.
    assert set(ids) == {1, 2, 3}
    assert ids[-1] == 1
    # scores are descending
    assert fused[0]["score"] >= fused[1]["score"] >= fused[2]["score"]


def test_fuse_rrf_keeps_vector_only_hit_with_lower_score():
    vec_hits = [{"id": 9, "text": "x", "source_id": "s", "conversation_id": None, "score": 0.05, "chunk_index": 0}]
    lex_hits = [{"id": 10, "text": "y", "source_id": "s", "conversation_id": None, "score": 1.0, "chunk_index": 0}]
    fused = rag_service._fuse_rrf(vec_hits, lex_hits, top_k=5)
    assert {row["id"] for row in fused} == {9, 10}


def test_fuse_rrf_respects_top_k():
    vec_hits = [
        {"id": i, "text": str(i), "source_id": "s", "conversation_id": None, "score": 0.0, "chunk_index": i}
        for i in range(5)
    ]
    fused = rag_service._fuse_rrf(vec_hits, [], top_k=2)
    assert len(fused) == 2
