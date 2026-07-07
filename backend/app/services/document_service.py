"""Extracts plain text from uploaded documents so it can be dropped into
the chat context. Kept intentionally simple (no vector DB / RAG) — chunks
are truncated to `doc_chunk_chars` and, for longer docs, summarized first
using the general model before being handed to the router's chosen model.
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import settings

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext in {".txt", ".md", ".csv", ".json"}:
        return path.read_text(errors="ignore")
    raise ValueError(f"Unsupported document type: {ext}")


def _extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages):
        pages.append(f"--- page {i + 1} ---\n{page.extract_text() or ''}")
    return "\n".join(pages)


def _extract_docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def chunk_for_context(text: str) -> str:
    """Truncates long documents to a safe context size, keeping head + tail
    (where titles/intros and conclusions/totals usually live)."""
    limit = settings.get("doc_chunk_chars", 6000)
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n\n... [document truncated, {len(text) - limit} chars omitted] ...\n\n{tail}"
