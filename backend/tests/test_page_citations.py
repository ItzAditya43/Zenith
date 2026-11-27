from __future__ import annotations

from app.services import rag_service


def test_chunks_carry_pages(monkeypatch):
    monkeypatch.setattr(rag_service, "settings", {"rag_chunk_chars": 200, "rag_chunk_overlap": 20} | {})  # type: ignore[arg-type]
    text = "\n".join(f"--- page {n} ---\n" + ("word " * 50) for n in range(1, 4))
    chunks = rag_service._with_pages(text, rag_service._chunk_text(text))
    assert chunks[0].startswith("(page 1) ")
    assert rag_service.page_of(chunks[-1]) in ("3", "2-3")
    assert any("-" in (rag_service.page_of(c) or "") for c in chunks)
    assert rag_service._with_pages("no pages here", ["no pages here"]) == ["no pages here"]
