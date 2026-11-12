"""Structured code search for the agent's `grep` and `glob` tools.

Small local models are unreliable at composing `grep -rn ... --include`
through `bash`, and the output of a raw recursive grep floods a small
context window with `node_modules` hits. These helpers do the search
in-process: noise directories and binary files are skipped, results are
capped, and paths come back relative to the working directory so they can
be passed straight to `read_file`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".idea", "coverage",
}
MAX_FILE_BYTES = 1_000_000
MAX_FILES_SCANNED = 20_000
MAX_GREP_MATCHES = 100
MAX_GLOB_RESULTS = 200
MAX_LINE_CHARS = 200


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """`**` crosses directories, `*` and `?` stay inside one path segment."""
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _matcher(pattern: str):
    """A pattern without a slash matches the file name at any depth
    (`*.py` finds every Python file); one with a slash matches the path
    relative to the search root."""
    pattern = pattern.strip().removeprefix("./")
    rx = _glob_to_regex(pattern)
    if "/" in pattern:
        return lambda rel: rx.match(rel) is not None
    return lambda rel: rx.match(rel.rsplit("/", 1)[-1]) is not None


def _walk(root: Path):
    """Yield (path, path relative to root) for regular files under `root`,
    skipping noise directories and anything that resolves outside `root`
    (a symlink must not turn a search into a read of the rest of the disk)."""
    if root.is_file():
        yield root, root.name
        return
    real_root = root.resolve()
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.is_symlink():
                try:
                    target = p.resolve()
                except (OSError, RuntimeError):
                    continue
                if real_root not in target.parents:
                    continue
            if not p.is_file():
                continue
            seen += 1
            if seen > MAX_FILES_SCANNED:
                return
            yield p, p.relative_to(root).as_posix()


def _display(path: Path, base: Path | None) -> str:
    if base is not None:
        try:
            return path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


def glob_files(root: Path, pattern: str, base: Path | None = None) -> str:
    if not pattern.strip():
        return "Error: no pattern given."
    if not root.exists():
        return f"Error: {root} does not exist."
    match = _matcher(pattern)
    found = [_display(p, base) for p, rel in _walk(root) if match(rel)]
    if not found:
        return f"No files match {pattern!r}."
    lines = found[:MAX_GLOB_RESULTS]
    if len(found) > MAX_GLOB_RESULTS:
        lines.append(f"... {len(found) - MAX_GLOB_RESULTS} more files not shown; use a narrower pattern.")
    return "\n".join(lines)


def grep_files(
    root: Path, pattern: str, glob: str = "", ignore_case: bool = False, base: Path | None = None,
) -> str:
    if not pattern:
        return "Error: no pattern given."
    if not root.exists():
        return f"Error: {root} does not exist."
    flags = re.IGNORECASE if ignore_case else 0
    note = ""
    try:
        rx = re.compile(pattern, flags)
    except re.error:
        # Models often pass code as the pattern ("foo(", "a[i]"); searching
        # for it literally is what they meant.
        rx = re.compile(re.escape(pattern), flags)
        note = "(pattern is not a valid regex; searched for it as literal text)\n"
    match = _matcher(glob) if glob.strip() else None

    lines: list[str] = []
    total = 0
    for p, rel in _walk(root):
        if match is not None and not match(rel):
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue  # binary
        shown = _display(p, base)
        for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if rx.search(line):
                total += 1
                if total <= MAX_GREP_MATCHES:
                    lines.append(f"{shown}:{n}: {line.strip()[:MAX_LINE_CHARS]}")
    if not total:
        return note + f"No matches for {pattern!r}."
    if total > MAX_GREP_MATCHES:
        lines.append(f"... {total - MAX_GREP_MATCHES} more matches not shown; narrow the pattern, path or glob.")
    return note + "\n".join(lines)
