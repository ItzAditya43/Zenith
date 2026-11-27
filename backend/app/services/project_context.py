"""Project code context: a searchable index of a project's code and docs,
used to give coding conversations the few snippets that matter — each
cited as path:start-end — plus what recent agent runs changed.

Indexing is explicit (Workspace → Index project) and incremental: files
are split into ~60-line blocks on blank-line boundaries and stored in the
same retrieval index as documents (source kind "code"); a re-index only
re-reads files whose size or modification time changed, and drops files
that were deleted. Architecture notes count: README, docs/, ADRs and other
Markdown are indexed alongside code.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from app.core.logging import get_logger
from app.db.storage import _conn
from app.services import code_search, repo_map

log = get_logger(__name__)

DOC_EXTS = {".md", ".mdx", ".rst", ".txt", ".adoc"}
MAX_FILES = 3000
MAX_FILE_BYTES = 300_000
BLOCK_LINES = 60
KIND = "code"

_progress: dict[str, dict] = {}


def project_key(workdir: str | Path) -> str:
    return hashlib.sha1(str(Path(workdir).resolve()).encode()).hexdigest()[:12]


def _ensure_table() -> None:
    with _conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS code_index_files (
                project TEXT NOT NULL, path TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
                blocks INTEGER NOT NULL, indexed_at REAL NOT NULL, PRIMARY KEY (project, path))"""
        )


def blocks(text: str, max_lines: int = BLOCK_LINES) -> list[tuple[int, int, str]]:
    """[(start, end, text)] — ~max_lines per block, cut at a blank line
    when one is near, so functions mostly stay whole. Lines are 1-based."""
    lines = text.splitlines()
    out, start = [], 0
    while start < len(lines):
        end = min(len(lines), start + max_lines)
        if end < len(lines):
            for cut in range(end, max(start + max_lines // 2, start + 1), -1):
                if not lines[cut - 1].strip():
                    end = cut
                    break
        chunk = "\n".join(lines[start:end]).strip()
        if chunk:
            out.append((start + 1, end, chunk))
        start = end
    return out


def _wanted(p: Path) -> bool:
    return p.suffix.lower() in repo_map.SOURCE_EXTS or p.suffix.lower() in DOC_EXTS


def index_project(workdir: str) -> dict:
    """(Re)index changed files. Blocking — run in a thread."""
    from app.services import rag_service

    _ensure_table()
    root = Path(workdir).resolve()
    key = project_key(root)
    state = _progress[key] = {"status": "running", "done": 0, "total": 0, "changed": 0, "removed": 0, "started": time.time()}
    with _conn() as conn:
        known = {r["path"]: (r["mtime_ns"], r["size"]) for r in conn.execute(
            "SELECT path, mtime_ns, size FROM code_index_files WHERE project = ?", (key,))}
    files = []
    for p, rel in code_search._walk(root):  # noqa: SLF001 — same ignore rules as search
        if _wanted(p):
            files.append((p, rel))
            if len(files) >= MAX_FILES:
                break
    state["total"] = len(files)
    seen = set()
    try:
        for p, rel in files:
            seen.add(rel)
            st = p.stat()
            if known.get(rel) == (st.st_mtime_ns, st.st_size) or st.st_size > MAX_FILE_BYTES:
                state["done"] += 1
                continue
            text = p.read_text(errors="ignore")
            rag_service._delete_chunks("source_kind = ? AND source_id LIKE ?", (KIND, f"{key}::{rel}::%"))  # noqa: SLF001
            n = 0
            for a, b, chunk in blocks(text):
                rag_service.index_document(f"{key}::{rel}::{a}-{b}", f"{rel} (lines {a}-{b})\n{chunk}", None, source_kind=KIND)
                n += 1
            with _conn() as conn:
                conn.execute("INSERT OR REPLACE INTO code_index_files (project, path, mtime_ns, size, blocks, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (key, rel, st.st_mtime_ns, st.st_size, n, time.time()))
            state["changed"] += 1
            state["done"] += 1
        for rel in set(known) - seen:
            rag_service._delete_chunks("source_kind = ? AND source_id LIKE ?", (KIND, f"{key}::{rel}::%"))  # noqa: SLF001
            with _conn() as conn:
                conn.execute("DELETE FROM code_index_files WHERE project = ? AND path = ?", (key, rel))
            state["removed"] += 1
        state["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        log.warning("project_context.index_failed", error=str(exc))
        state.update(status="failed", error=str(exc))
    state["finished"] = time.time()
    return state


def status(workdir: str) -> dict:
    _ensure_table()
    key = project_key(workdir)
    with _conn() as conn:
        r = conn.execute("SELECT COUNT(*) AS files, COALESCE(SUM(blocks),0) AS blocks, MAX(indexed_at) AS last FROM code_index_files WHERE project = ?",
                         (key,)).fetchone()
    return {"indexed_files": r["files"], "blocks": r["blocks"], "last_indexed": r["last"], "run": _progress.get(key)}


def retrieve(workdir: str, query: str, top_k: int = 5) -> list[dict]:
    """The most relevant code/doc blocks in this project, with citations."""
    from app.services import rag_service

    key = project_key(workdir)
    hits = rag_service.retrieve(query, None, top_k * 6, KIND)
    out = []
    for h in hits:
        sid = h.get("source_id") or ""
        if not sid.startswith(f"{key}::"):
            continue
        _, rel, rng = sid.split("::", 2)
        a, _, b = rng.partition("-")
        text = h["text"].split("\n", 1)[1] if "\n" in h["text"] else h["text"]
        out.append({"path": rel, "start": int(a or 1), "end": int(b or a or 1), "text": text})
        if len(out) >= top_k:
            break
    return out


def recent_runs(conversation_id: str, limit: int = 3) -> list[dict]:
    """What the last few agent runs in this chat asked for and changed."""
    with _conn() as conn:
        runs = conn.execute(
            """SELECT run_id, MIN(created_at) AS at FROM tool_calls WHERE conversation_id = ? AND run_id IS NOT NULL
               GROUP BY run_id ORDER BY at DESC LIMIT ?""", (conversation_id, limit)).fetchall()
        out = []
        for r in runs:
            files = sorted({json.loads(a["args"]).get("path", "?") for a in conn.execute(
                "SELECT args FROM tool_calls WHERE run_id = ? AND tool IN ('edit_file','write_file') AND status = 'executed'", (r["run_id"],))})
            ask = conn.execute("SELECT content FROM messages WHERE id = ?", (r["run_id"],)).fetchone()
            out.append({"asked": (ask["content"] if ask else "")[:160], "files": files[:10], "at": r["at"]})
    return out


def context_block(conversation_id: str, workdir: str | None, query: str) -> tuple[str, list[dict]]:
    """System-prompt section + citations for a coding conversation. Empty
    when the project hasn't been indexed and there are no past runs."""
    if not workdir:
        return "", []
    parts, cites = [], []
    try:
        if status(workdir)["indexed_files"]:
            for h in retrieve(workdir, query):
                parts.append(f"[{h['path']}:{h['start']}-{h['end']}]\n{h['text'][:1500]}")
                cites.append({"kind": "code", "path": h["path"], "start": h["start"], "end": h["end"],
                              "text": h["text"][:300], "source_id": f"{h['path']}:{h['start']}"})
    except Exception as exc:  # noqa: BLE001
        log.debug("project_context.retrieve_failed", error=str(exc))
    runs = recent_runs(conversation_id)
    sections = []
    if parts:
        sections.append("Relevant code and notes from this project (cite as path:line when you use them):\n\n" + "\n\n".join(parts))
    if runs:
        sections.append("Recent agent runs in this chat:\n" + "\n".join(
            f"- asked: {r['asked']!r}; changed: {', '.join(r['files']) or 'nothing'}" for r in runs))
    return "\n\n".join(sections), cites
