"""Batch jobs: run one prompt template against every file in a folder,
one file at a time, and stream back a result per file.

Distinct from folder_service.py's watcher (which indexes files into RAG
so they're recalled *reactively* during chat) — this is the explicit,
one-shot "summarize each of these 20 meeting notes" / "extract action
items from every file in this folder" operation. Nothing here touches
the RAG store or gets persisted; it's a live streamed job.

Non-recursive by design: `folder_path` is scanned one level deep only.
A batch job is meant for "this folder of notes", not an arbitrary
subtree walk — recursing silently into nested directories (and possibly
picking up a `.git`, `node_modules`, etc.) is more surprising than
useful here, and non-recursive keeps the cap (below) meaningful as a
predictable bound on one directory's contents.
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from app.core.logging import get_logger
from app.services.ollama_client import OllamaClient, OllamaError

log = get_logger(__name__)

# Sane upper bound so an accidental point-at-huge-folder doesn't turn into
# a runaway multi-hour job against the local model. Anything beyond this
# many matching files gets a single trailing error entry, not silent
# truncation — the caller finds out the job was capped.
MAX_BATCH_FILES = 100

# Only plain-text-ish files are handled directly (a simple read, no PDF/
# docx extraction machinery — see document_service.py for that, but this
# job is for text/markdown/code notes, not binary documents).
_READABLE_EXTS = {".txt", ".md", ".markdown", ".csv", ".json", ".py", ".js",
                   ".ts", ".jsx", ".tsx", ".log", ".yaml", ".yml"}

_MAX_FILE_CHARS = 20_000  # keep a single file's content within a sane prompt budget


def _safe_folder(folder_path: str) -> Path:
    """Resolves `folder_path` and rejects anything that doesn't cleanly
    resolve to a real, existing directory. Mirrors the same "no `../`
    escape" spirit as app/api/files.py's `_safe_resolve`: there the
    concern is escaping a *bound root*; here there's no bound root (the
    user can point this at any folder the backend process can see, same
    as folder_service.add_watched_folder), so the check is instead that
    the path doesn't contain a literal `..` traversal segment sneaking
    around a naive prefix check, and that it resolves to a real directory
    rather than silently no-op'ing on a bogus path."""
    if ".." in Path(folder_path).parts:
        raise ValueError("Path escapes are not allowed (no '..' segments).")
    p = Path(folder_path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        raise ValueError(f"Not a directory (or not visible to the backend process): {folder_path}")
    return p


def _list_batch_files(root: Path, extensions: list[str] | None) -> list[Path]:
    if extensions:
        allowed = {("." + e.lstrip(".")).lower() for e in extensions}
    else:
        allowed = _READABLE_EXTS
    files = sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in allowed
    )
    return files


async def run_batch(
    folder_path: str,
    prompt_template: str,
    model: str,
    extensions: list[str] | None = None,
) -> AsyncIterator[dict]:
    """Yields one result dict per file as it completes:
      {"file": <path>, "status": "done", "result": <model output text>}
      {"file": <path>, "status": "error", "error": <message>}

    `prompt_template` is combined with each file's content as:
      "<prompt_template>\\n\\n---\\nFile: <name>\\n---\\n<content>"

    Non-recursive: only files directly inside `folder_path` are considered.
    """
    try:
        root = _safe_folder(folder_path)
    except ValueError as exc:
        yield {"file": folder_path, "status": "error", "error": str(exc)}
        return

    try:
        files = _list_batch_files(root, extensions)
    except OSError as exc:
        yield {"file": folder_path, "status": "error", "error": f"Could not list folder: {exc}"}
        return

    if not files:
        yield {"file": str(root), "status": "error", "error": "No matching files found in this folder."}
        return

    capped = files[:MAX_BATCH_FILES]
    overflow = len(files) - len(capped)

    client = OllamaClient()
    for path in capped:
        file_str = str(path)
        try:
            text = path.read_text(errors="ignore")
            if len(text) > _MAX_FILE_CHARS:
                text = text[:_MAX_FILE_CHARS] + f"\n\n... [truncated, {len(text) - _MAX_FILE_CHARS} chars omitted] ..."
            prompt = f"{prompt_template}\n\n---\nFile: {path.name}\n---\n{text}"
            result = await client.chat(model, [{"role": "user", "content": prompt}])
            yield {"file": file_str, "status": "done", "result": result}
        except OllamaError as exc:
            yield {"file": file_str, "status": "error", "error": str(exc)}
        except Exception as exc:
            log.warning("batch.file_failed", file=file_str, error=str(exc))
            yield {"file": file_str, "status": "error", "error": str(exc)}

    if overflow > 0:
        yield {
            "file": f"(+{overflow} more)",
            "status": "error",
            "error": f"Batch capped at {MAX_BATCH_FILES} files — {overflow} additional matching "
                     f"file(s) in this folder were not processed.",
        }
