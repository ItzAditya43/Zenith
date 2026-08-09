"""Folder watcher: point Zenith at a directory (a notes vault, a repo)
and it periodically re-scans and indexes matching files into the RAG
store, so they're recalled during chat like any other knowledge —
without a manual upload per file.

Runs entirely against whatever filesystem the backend process can see.
In the Docker deployment that's the container's own filesystem unless
you've added a host bind mount (see docker-compose.yml, same tradeoff
documented there for agent mode's bash/file tools).
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from app.core.logging import get_logger
from app.db.storage import _conn

log = get_logger(__name__)

DEFAULT_EXTENSIONS = ".md,.txt,.py,.js,.ts,.json"
_SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def list_watched_folders() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM watched_folders ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]


def get_watched_folder(folder_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM watched_folders WHERE id = ?", (folder_id,)).fetchone()
        return dict(row) if row else None


def add_watched_folder(path: str, extensions: str | None = None) -> dict:
    p = Path(path).expanduser()
    if not p.exists() or not p.is_dir():
        raise ValueError(f"Not a directory (or not visible to the backend process): {path}")
    resolved = str(p.resolve())
    fid = str(uuid.uuid4())
    now = time.time()
    exts = extensions or DEFAULT_EXTENSIONS
    with _conn() as conn:
        existing = conn.execute("SELECT id FROM watched_folders WHERE path = ?", (resolved,)).fetchone()
        if existing:
            raise ValueError("This folder is already being watched.")
        conn.execute(
            "INSERT INTO watched_folders (id, path, extensions, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
            (fid, resolved, exts, now),
        )
    return {"id": fid, "path": resolved, "extensions": exts, "enabled": 1,
            "last_scanned_at": None, "created_at": now}


def remove_watched_folder(folder_id: str) -> None:
    from app.services import rag_service

    with _conn() as conn:
        rows = conn.execute("SELECT path FROM watched_files WHERE folder_id = ?", (folder_id,)).fetchall()
        for r in rows:
            rag_service.delete_folder_chunks(r["path"])
        conn.execute("DELETE FROM watched_files WHERE folder_id = ?", (folder_id,))
        conn.execute("DELETE FROM watched_folders WHERE id = ?", (folder_id,))


def set_folder_enabled(folder_id: str, enabled: bool) -> None:
    with _conn() as conn:
        conn.execute("UPDATE watched_folders SET enabled = ? WHERE id = ?", (1 if enabled else 0, folder_id))


def _get_file_record(path: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM watched_files WHERE path = ?", (path,)).fetchone()
        return dict(row) if row else None


def _upsert_file_record(conn, path: str, folder_id: str, mtime: float) -> None:
    now = time.time()
    conn.execute(
        "INSERT INTO watched_files (path, folder_id, mtime, indexed_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, indexed_at = excluded.indexed_at",
        (path, folder_id, mtime, now),
    )


def scan_folder(folder: dict) -> dict:
    """Walks `folder['path']`, indexing any file matching its extensions
    whose mtime is newer than what's recorded. Returns a summary dict —
    never raises; per-file errors are collected, not fatal."""
    from app.services import rag_service

    exts = {e.strip().lower() for e in folder["extensions"].split(",") if e.strip()}
    root = Path(folder["path"])
    scanned = indexed = 0
    errors: list[str] = []
    if not root.exists():
        return {"scanned": 0, "indexed": 0, "errors": [f"Folder no longer exists: {root}"]}

    seen_paths: set[str] = set()
    new_files: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        scanned += 1
        abs_path = str(path.resolve())
        seen_paths.add(abs_path)
        try:
            mtime = path.stat().st_mtime
            existing = _get_file_record(abs_path)
            if existing and existing["mtime"] >= mtime:
                continue
            text = path.read_text(errors="ignore")
            if not text.strip():
                continue
            rag_service.index_folder_file(abs_path, text, folder["id"])
            with _conn() as conn:
                _upsert_file_record(conn, abs_path, folder["id"], mtime)
            indexed += 1
            if existing is None:
                new_files.append(abs_path)
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    # Files that were indexed before but no longer exist/match — drop
    # their chunks so deleted/renamed notes don't linger in recall.
    with _conn() as conn:
        stale = conn.execute(
            "SELECT path FROM watched_files WHERE folder_id = ?", (folder["id"],)
        ).fetchall()
        for r in stale:
            if r["path"] not in seen_paths:
                rag_service.delete_folder_chunks(r["path"])
                conn.execute("DELETE FROM watched_files WHERE path = ?", (r["path"],))

    with _conn() as conn:
        conn.execute(
            "UPDATE watched_folders SET last_scanned_at = ? WHERE id = ?", (time.time(), folder["id"])
        )
    log.info("folder.scanned", folder_id=folder["id"], path=folder["path"],
              scanned=scanned, indexed=indexed, errors=len(errors))
    return {"scanned": scanned, "indexed": indexed, "errors": errors, "new_files": new_files}


async def scan_all_enabled() -> None:
    import asyncio
    from app.services import events

    for folder in list_watched_folders():
        if folder["enabled"]:
            try:
                result = await asyncio.to_thread(scan_folder, folder)
                if result.get("new_files"):
                    await events.emit("folder_file_added", {
                        "folder_id": folder["id"], "folder_path": folder["path"],
                        "files": result["new_files"],
                    })
            except Exception as exc:
                log.warning("folder.scan_failed", folder_id=folder["id"], error=str(exc))
