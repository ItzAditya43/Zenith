"""Code intelligence for the workspace: symbol search, go-to-definition,
find-references, and project-wide type checks.

Symbols come from the same parsing the repo map uses — Python's `ast`,
per-line declaration regexes for other languages — so it needs no
language server and behaves the same everywhere. References are a
word-boundary text search: fast and dependable, though it can't tell two
different things with the same name apart (the UI says so).

`project_check` runs the project's own type checkers when they're
installed — mypy or pyright for Python, tsc for TypeScript, `cargo check`
for Rust, `go vet` for Go — and turns their output into one list of
problems with file, line and message. It's on demand (or after an agent
edit when enabled), never in the background.
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import shutil
from pathlib import Path

from app.services import code_search, repo_map

MAX_REFS = 300
CHECK_TIMEOUT = 180.0
_NAME = re.compile(r"(?:def|class|function|fn|func|struct|enum|trait|interface|type|mod|module|const|let|var|object|record|protocol|extension|impl(?:<[^>]*>)?)\s+([A-Za-z_][\w]*)")
_KIND = re.compile(r"\b(class|def|function|fn|func|struct|enum|trait|interface|type|mod|module|impl|object|record|protocol)\b")

# path -> (mtime_ns, size, [(name, kind, line)])
_cache: dict[str, tuple[int, int, list[tuple[str, str, int]]]] = {}


def _python(source: str) -> list[tuple[str, str, int]]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out: list[tuple[str, str, int]] = []

    def visit(node: ast.AST, parent: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                out.append((child.name, "class", child.lineno))
                visit(child, child.name)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((child.name, "method" if parent else "function", child.lineno))
            elif isinstance(child, ast.Assign) and parent is None:
                for t in child.targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        out.append((t.id, "constant", child.lineno))
    visit(tree, None)
    return out


def _regex(source: str, pattern: re.Pattern[str]) -> list[tuple[str, str, int]]:
    out = []
    for i, line in enumerate(source.splitlines(), 1):
        m = pattern.match(line)
        if not m:
            continue
        decl = m.group(2)
        nm = _NAME.search(decl)
        if not nm:
            # C-style "type name(args)" — take the identifier before "("
            c = re.search(r"([A-Za-z_][\w:~]*)\s*\(", decl)
            if not c:
                continue
            name = c.group(1).split("::")[-1]
        else:
            name = nm.group(1)
        k = _KIND.search(decl)
        out.append((name, (k.group(1) if k else "function"), i))
    return out


def file_symbols(path: Path) -> list[tuple[str, str, int]]:
    try:
        st = path.stat()
    except OSError:
        return []
    key = str(path)
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    if st.st_size > 1_500_000:
        return []
    try:
        source = path.read_text(errors="ignore")
    except OSError:
        return []
    ext = path.suffix.lower()
    syms = _python(source) if ext == ".py" else _regex(source, repo_map._PATTERNS[ext]) if ext in repo_map._PATTERNS else []  # noqa: SLF001
    if len(_cache) > 8000:
        _cache.clear()
    _cache[key] = (st.st_mtime_ns, st.st_size, syms)
    return syms


def _source_files(root: Path):
    for p, rel in code_search._walk(root):  # noqa: SLF001 — same ignore rules as search
        if p.suffix.lower() in repo_map.SOURCE_EXTS:
            yield p, rel


def _fuzzy(q: str, name: str) -> float:
    ql, nl = q.lower(), name.lower()
    if nl == ql:
        return 100
    if nl.startswith(ql):
        return 80 - len(nl) / 100
    if ql in nl:
        return 60 - nl.index(ql) / 10
    it = iter(nl)
    if all(c in it for c in ql):  # subsequence: "gcs" -> get_conversation_state
        return 30 - len(nl) / 100
    return 0


def symbols(root: Path, query: str, limit: int = 50) -> list[dict]:
    scored = []
    for p, rel in _source_files(root):
        for name, kind, line in file_symbols(p):
            s = _fuzzy(query, name) if query else 1
            if s > 0:
                scored.append((s, {"name": name, "kind": kind, "path": rel, "line": line}))
    scored.sort(key=lambda x: (-x[0], x[1]["path"], x[1]["line"]))
    return [d for _, d in scored[:limit]]


def definitions(root: Path, name: str) -> list[dict]:
    out = []
    for p, rel in _source_files(root):
        for n, kind, line in file_symbols(p):
            if n == name:
                out.append({"name": n, "kind": kind, "path": rel, "line": line})
    return out


def references(root: Path, name: str, limit: int = MAX_REFS) -> dict:
    if not re.fullmatch(r"[A-Za-z_]\w*", name or ""):
        return {"results": [], "truncated": False}
    word = re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")
    defs = {(d["path"], d["line"]) for d in definitions(root, name)}
    out, truncated = [], False
    for p, rel in _source_files(root):
        try:
            with p.open(errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    if word.search(line):
                        out.append({"path": rel, "line": i, "text": line.strip()[:200], "definition": (rel, i) in defs})
                        if len(out) >= limit:
                            truncated = True
                            return {"results": out, "truncated": truncated}
        except OSError:
            continue
    return {"results": out, "truncated": truncated}


# ---- project-wide checks ---------------------------------------------------------

_LINE = re.compile(r"^(?P<path>[^:\n()]+?)[:(](?P<line>\d+)[:,](?P<col>\d+)?\)?:?\s*(?:-\s*)?(?P<sev>error|warning|note|E\d+|W\d+|F\d+)?:?\s*(?P<msg>.+)$")


def _parse(out: str, root: Path, tool: str) -> list[dict]:
    problems = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.startswith(("Found ", "Success", "error: could not compile", "warning: build failed")):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        path = m.group("path").strip()
        try:
            rel = Path(path).resolve().relative_to(root).as_posix() if os.path.isabs(path) else path.lstrip("./")
        except ValueError:
            continue
        if not (root / rel).exists():
            continue
        msg = m.group("msg").strip()
        sev = (m.group("sev") or "").lower()
        severity = "warning" if sev.startswith("warn") or sev.startswith("w") else "note" if sev == "note" else "error"
        problems.append({"path": rel, "line": int(m.group("line")), "col": int(m.group("col") or 1),
                         "severity": severity, "message": msg[:400], "source": tool})
    return problems


def available_checks(root: Path) -> list[tuple[str, list[str]]]:
    """(tool, argv) for each checker that applies to this project and is installed."""
    checks: list[tuple[str, list[str]]] = []
    has = lambda *names: any((root / n).exists() for n in names)  # noqa: E731
    py = has("pyproject.toml", "setup.py", "setup.cfg", "mypy.ini", "requirements.txt") or any(root.glob("*.py"))
    if py:
        if shutil.which("pyright"):
            checks.append(("pyright", ["pyright", "."]))
        elif shutil.which("mypy"):
            checks.append(("mypy", ["mypy", ".", "--no-error-summary", "--show-column-numbers", "--hide-error-context",
                                    "--no-pretty", "--ignore-missing-imports", "--explicit-package-bases"]))
    if has("tsconfig.json"):
        local = root / "node_modules" / ".bin" / "tsc"
        tsc = str(local) if local.exists() else shutil.which("tsc")
        if tsc:
            checks.append(("tsc", [tsc, "--noEmit", "--pretty", "false", "-p", "."]))
    if has("Cargo.toml") and shutil.which("cargo"):
        checks.append(("cargo", ["cargo", "check", "--message-format=short", "--quiet"]))
    if has("go.mod") and shutil.which("go"):
        checks.append(("go vet", ["go", "vet", "./..."]))
    return checks


async def project_check(root: Path, timeout: float = CHECK_TIMEOUT, fresh: bool = False) -> dict:
    """`fresh` skips mypy's incremental cache. The agent loop needs it: mypy
    trusts a cached file whose size and whole-second mtime are unchanged,
    and an agent can rewrite a file twice in one second at the same length."""
    checks = available_checks(root)
    if fresh:
        checks = [(t, argv + ["--no-incremental"] if t == "mypy" else argv) for t, argv in checks]
    ran, problems, notes = [], [], []
    for tool, argv in checks:
        try:
            proc = await asyncio.create_subprocess_exec(*argv, cwd=str(root), stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout)
            except TimeoutError:
                proc.kill()
                notes.append(f"{tool} took longer than {int(timeout)}s and was stopped.")
                continue
        except OSError as exc:
            notes.append(f"{tool} couldn't start: {exc}")
            continue
        text = out.decode(errors="ignore")
        found = _parse(text, root, tool)
        if not found and proc.returncode not in (0, 1):
            tail = "\n".join(text.strip().splitlines()[-4:])
            notes.append(f"{tool} couldn't check this project (exit {proc.returncode}): {tail[:400]}")
        problems += found
        ran.append({"tool": tool, "problems": len(found), "exit": proc.returncode})
    if not checks:
        notes.append("No type checker for this project is installed (mypy or pyright, tsc, cargo, go).")
    problems.sort(key=lambda p: (p["severity"] != "error", p["path"], p["line"]))
    return {"ran": ran, "problems": problems[:500], "notes": notes}
