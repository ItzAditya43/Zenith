"""Unit tests for rag_service's optional cross-encoder-style rerank pass.
No live Ollama needed — _rerank_sync / _resolve_rerank_model are mocked so
these only exercise the pure gating, scoring, and fallback logic."""
from app.services import rag_service


def _candidates(n):
    return [
        {"id": i, "text": f"chunk {i}", "source_id": "s", "conversation_id": None,
         "score": 1.0 / (i + 1), "chunk_index": i}
        for i in range(n)
    ]


def test_maybe_rerank_disabled_by_default_returns_original_order(monkeypatch):
    monkeypatch.setattr(rag_service.settings, "get",
                         lambda key, default=None: False if key == "rag_rerank_enabled" else default)
    candidates = _candidates(10)
    out = rag_service._maybe_rerank("query", candidates, top_k=3)
    assert [c["id"] for c in out] == [0, 1, 2]


def test_maybe_rerank_skips_when_not_more_candidates_than_top_k(monkeypatch):
    settings_map = {"rag_rerank_enabled": True, "rag_rerank_pool": 15}
    monkeypatch.setattr(rag_service.settings, "get", lambda key, default=None: settings_map.get(key, default))

    called = {"n": 0}

    def fake_rerank_sync(query, pool):
        called["n"] += 1
        return None

    monkeypatch.setattr(rag_service, "_rerank_sync", fake_rerank_sync)
    candidates = _candidates(3)
    out = rag_service._maybe_rerank("query", candidates, top_k=3)
    assert [c["id"] for c in out] == [0, 1, 2]
    assert called["n"] == 0  # reranking is pointless when nothing would be trimmed


def test_maybe_rerank_reorders_by_rerank_score(monkeypatch):
    settings_map = {"rag_rerank_enabled": True, "rag_rerank_pool": 15}
    monkeypatch.setattr(rag_service.settings, "get", lambda key, default=None: settings_map.get(key, default))
    candidates = _candidates(5)

    def fake_rerank_sync(query, pool):
        # Reverse the input order and attach descending scores, simulating
        # a cross-encoder disagreeing with the fused pre-rank order.
        out = []
        for score, cand in enumerate(reversed(pool)):
            row = dict(cand)
            row["score"] = float(score)
            out.append(row)
        return out

    monkeypatch.setattr(rag_service, "_rerank_sync", fake_rerank_sync)
    out = rag_service._maybe_rerank("query", candidates, top_k=3)
    assert [c["id"] for c in out] == [4, 3, 2]


def test_maybe_rerank_falls_back_on_exception(monkeypatch):
    settings_map = {"rag_rerank_enabled": True, "rag_rerank_pool": 15}
    monkeypatch.setattr(rag_service.settings, "get", lambda key, default=None: settings_map.get(key, default))

    def fake_rerank_sync(query, pool):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(rag_service, "_rerank_sync", fake_rerank_sync)
    candidates = _candidates(6)
    out = rag_service._maybe_rerank("query", candidates, top_k=4)
    # Falls back to the pre-rerank fused order, never raises.
    assert [c["id"] for c in out] == [0, 1, 2, 3]


def test_maybe_rerank_falls_back_when_rerank_sync_returns_none(monkeypatch):
    settings_map = {"rag_rerank_enabled": True, "rag_rerank_pool": 15}
    monkeypatch.setattr(rag_service.settings, "get", lambda key, default=None: settings_map.get(key, default))
    monkeypatch.setattr(rag_service, "_rerank_sync", lambda query, pool: None)
    candidates = _candidates(5)
    out = rag_service._maybe_rerank("query", candidates, top_k=2)
    assert [c["id"] for c in out] == [0, 1]


def test_parse_rerank_scores_happy_path():
    reply = "1: 87\n2: 42\n3: 5\n"
    scores = rag_service._parse_rerank_scores(reply, 3)
    assert scores == [87.0, 42.0, 5.0]


def test_parse_rerank_scores_clamps_out_of_range():
    reply = "1: 150\n2: -10\n"
    scores = rag_service._parse_rerank_scores(reply, 2)
    assert scores[0] == 100.0
    assert scores[1] >= 0.0


def test_parse_rerank_scores_returns_none_when_unparseable():
    assert rag_service._parse_rerank_scores("I refuse to answer.", 3) is None


def test_parse_rerank_scores_defaults_missing_lines_to_zero():
    reply = "1: 90\n"
    scores = rag_service._parse_rerank_scores(reply, 3)
    assert scores == [90.0, 0.0, 0.0]


def test_rerank_sync_returns_none_when_no_model_resolved(monkeypatch):
    monkeypatch.setattr(rag_service, "_resolve_rerank_model", lambda: None)
    out = rag_service._rerank_sync("query", _candidates(3))
    assert out is None
