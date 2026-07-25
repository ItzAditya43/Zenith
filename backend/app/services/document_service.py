"""Extracts plain text from uploaded documents so it can be dropped into
the chat context. Kept intentionally simple (no vector DB / RAG) — chunks
are truncated to `doc_chunk_chars` and, for longer docs, summarized first
using the general model before being handed to the router's chosen model.

Phase 4 additions:
- OCR fallback for image-only / scanned PDFs (tesseract → text).
- "Looks empty?" detection that triggers OCR even for normal PDFs.
- Multi-document synthesis: each document's chunk is budgeted
  proportionally and clearly labeled in the prompt.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.core.config import settings

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md", ".csv", ".json"}

# Editing writes the full document back out, which only round-trips
# losslessly for plain-text formats — .pdf/.docx have layout/formatting
# extract_text() already throws away, so "editing" them would silently
# discard everything but the text.
EDITABLE_EXTS = {".txt", ".md", ".csv", ".json"}

_EDIT_SYSTEM_PROMPT = """You are editing a document. Apply the user's instruction to the
document below and output ONLY the complete edited document — no commentary, no preamble,
no markdown code fences (unless the original document itself used them), no explanation of
what you changed. Preserve everything the instruction doesn't ask you to change."""


async def edit_document(text: str, instruction: str, model: str) -> str:
    """Applies a natural-language edit instruction to a document's full
    text using the given model and returns the complete edited text.
    One shot, not agentic — for the common case of "fix the grammar" /
    "add a section about X" / "reformat this as a table", not open-ended
    multi-step editing (that's what agent mode's write_file is for)."""
    from app.services.ollama_client import OllamaClient

    client = OllamaClient()
    prompt = f"{_EDIT_SYSTEM_PROMPT}\n\nInstruction: {instruction}\n\nDocument:\n{text}"
    out = await client.chat(model, [{"role": "user", "content": prompt}])
    edited = out.strip()
    # Strip a markdown fence the model added despite instructions, if the
    # original text didn't have one — common small-model habit.
    if edited.startswith("```") and not text.strip().startswith("```"):
        lines = edited.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        edited = "\n".join(lines).strip()
    return edited


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
    text = "\n".join(pages)
    # Phase 4 #1: if extraction came back essentially empty (scanned PDF
    # with no embedded text layer) and OCR is enabled, fall back to
    # rendering pages and running tesseract.
    if _looks_empty(text) and bool(settings.get("doc_ocr_fallback", True)):
        ocr_text = _ocr_pdf(path)
        if ocr_text.strip():
            text = ocr_text
    return text


def _looks_empty(text: str) -> bool:
    """Heuristic: < 50 visible chars per page on average means the PDF
    is image-only (scanned). Real text is much denser than that."""
    if not text:
        return True
    stripped = "".join(c for c in text if c.isalnum())
    return len(stripped) < 50


def _ocr_pdf(path: Path) -> str:
    """Render each page to a temp PNG, run tesseract on each, concatenate.
    Requires `pdftoppm` (poppler) and `tesseract` on PATH; if either is
    missing we fall back to an empty string and let the caller show a
    user-friendly error."""
    if not shutil.which("tesseract") or not shutil.which("pdftoppm"):
        return ""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        try:
            subprocess.run(
                ["pdftoppm", "-r", "200", str(path), str(td / "page")],
                check=True, capture_output=True, timeout=120,
            )
        except Exception:
            return ""
        out = []
        for png in sorted(td.glob("page-*.png")):
            try:
                res = subprocess.run(
                    ["tesseract", str(png), "-", "-l", "eng"],
                    check=True, capture_output=True, timeout=60,
                )
                out.append(res.stdout.decode("utf-8", errors="ignore"))
            except Exception:
                continue
        return "\n".join(out)


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


def synthesize_multi_doc(docs: list[dict]) -> str:
    """Combine multiple documents into a single prompt block where each
    document gets a proportional share of the budget and is clearly
    labeled. `docs` is a list of {"name": str, "text": str}."""
    if not docs:
        return ""
    if len(docs) == 1:
        return f"[Document '{docs[0]['name']}']\n{chunk_for_context(docs[0]['text'])}"
    per_doc_limit = settings.get("doc_chunk_chars", 6000) // max(1, len(docs))
    parts = []
    for d in docs:
        chunked = chunk_for_context(d["text"]) if len(d["text"]) <= per_doc_limit * 2 else (
            d["text"][: per_doc_limit // 2]
            + f"\n\n... [truncated, {len(d['text']) - per_doc_limit} chars omitted] ...\n\n"
            + d["text"][-per_doc_limit // 2 :]
        )
        parts.append(f"[Document '{d['name']}']\n{chunked}")
    return "\n\n".join(parts)