"""Workspace file browser + editor, for the code-editor panel.

Scoped strictly to the conversation's bound working directory (set via the
folder button in the header / project workdir) — this is a direct,
un-gated user action from a UI panel, not an agent tool call, so unlike
agent_service's read_file/write_file (which allow absolute paths by
design — see README's Safety model), every path here is resolved and
must stay inside the workdir. No conversation workdir bound -> 404,
nothing to browse.

  GET  /api/conversations/{id}/files            list a directory
  GET  /api/conversations/{id}/files/content     read a file's text
  PUT  /api/conversations/{id}/files/content     write a file's text
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import Field

from app.core.logging import get_logger
from app.db import storage
from app.models.schemas import StrictModel

log = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["files"])

# Directories never worth showing/scanning in a code-editor file tree.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2MB — a code editor, not a binary viewer


class FileWriteRequest(StrictModel):
    content: str = Field(max_length=2_000_000)


def _workdir(conversation_id: str) -> Path:
    wd = storage.get_conversation_workdir(conversation_id)
    if not wd:
        raise HTTPException(404, "This conversation has no working directory bound — set one from the folder button in the header first.")
    root = Path(wd).resolve()
    if not root.is_dir():
        raise HTTPException(404, f"Working directory no longer exists: {wd}")
    return root


def _safe_resolve(root: Path, rel_path: str) -> Path:
    """Resolve `rel_path` against `root`, rejecting anything that escapes
    it (../, symlink tricks, absolute paths) — the whole point of this
    endpoint vs. agent_service's is that it's un-gated, so it must not be
    able to reach outside the bound directory."""
    candidate = (root / rel_path.lstrip("/")).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(400, "Path escapes the working directory.")
    return candidate


@router.get("/conversations/{conversation_id}/files")
async def list_files(conversation_id: str, path: str = Query("")):
    root = _workdir(conversation_id)
    target = _safe_resolve(root, path)
    if not target.exists():
        raise HTTPException(404, "No such path.")
    if not target.is_dir():
        raise HTTPException(400, "Not a directory.")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if child.name in _SKIP_DIRS:
            continue
        entries.append({
            "name": child.name,
            "path": str(child.relative_to(root)),
            "is_dir": child.is_dir(),
        })
    return {"path": str(target.relative_to(root)), "entries": entries}


@router.get("/conversations/{conversation_id}/files/content")
async def read_file(conversation_id: str, path: str = Query(...)):
    root = _workdir(conversation_id)
    target = _safe_resolve(root, path)
    if not target.is_file():
        raise HTTPException(404, "No such file.")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(413, "File too large to edit here (2MB limit).")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(415, "Not a text file.")
    return {"path": path, "content": content}


@router.put("/conversations/{conversation_id}/files/content")
async def write_file(conversation_id: str, body: FileWriteRequest, path: str = Query(...)):
    root = _workdir(conversation_id)
    target = _safe_resolve(root, path)
    if target.is_dir():
        raise HTTPException(400, "That path is a directory.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    log.info("files.write", conversation_id=conversation_id, path=path, bytes=len(body.content))
    return {"path": path, "saved": True}


# --- Git status/diff + run-checks, for the code editor panel ---------------
# Reuses agent_service's own git/check-command runners (same trust level:
# read-only git inspection and the user's own configured check command, no
# arbitrary shell — not the full `bash` tool agent mode exposes).

from app.services.agent_service import _run_checks, _run_git  # noqa: E402


@router.get("/conversations/{conversation_id}/git/status")
async def git_status(conversation_id: str):
    root = _workdir(conversation_id)
    out = await _run_git({"op": "status"}, timeout=15, max_chars=8000, workdir=str(root))
    return {"output": out}


@router.get("/conversations/{conversation_id}/git/diff")
async def git_diff(conversation_id: str, path: str = Query("")):
    root = _workdir(conversation_id)
    args = {"op": "diff"}
    if path:
        args["path"] = path
    out = await _run_git(args, timeout=15, max_chars=20000, workdir=str(root))
    return {"output": out}


@router.post("/conversations/{conversation_id}/run")
async def run_checks(conversation_id: str, body: dict | None = None):
    """Runs the configured check command (Settings -> Agent tools), or an
    explicit one-off `command` in the request body, in the bound working
    directory."""
    root = _workdir(conversation_id)
    out = await _run_checks(body or {}, workdir=str(root))
    return {"output": out}
