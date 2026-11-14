"""Repo map: a compact outline of the working directory's source files and
the symbols they define, added to the agent's system prompt.

A local model with a small context window can't read a repository to find
out where things live, and exploring with list_dir/read_file burns its
tool-call budget. The map answers "which file defines X?" up front.

Python is parsed with `ast`; other languages use per-line declaration
regexes. That's deliberate: it needs no native parser dependency, so it
behaves the same in Docker, a venv and the frozen desktop build. The cost
is that regex outlines can miss unusual declarations — the map is a guide
to what to read, not a source of truth.

The output is fitted to a character budget: every file path first, then
top-level symbols for as many files as fit (application code before tests,
shallow before deep), then methods.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from app.services import code_search

MAX_MAP_FILES = 400
MAX_SYMBOLS_PER_FILE = 40
MAX_SOURCE_BYTES = 400_000
MAX_SIG_CHARS = 110

Symbol = tuple[int, str]  # (depth: 0 top-level / 1 nested, declaration text)

_JS = re.compile(
    r"^(\s*)((?:export\s+)?(?:default\s+)?(?:"
    r"(?:async\s+)?function\s*\*?\s*\w+\s*\([^)]*\)?"
    r"|(?:abstract\s+)?class\s+\w+(?:\s+extends\s+[\w.]+)?"
    r"|(?:interface|enum|type)\s+\w+"
    r"|(?:const|let|var)\s+\w+\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*(?::[^=]+)?=>"
    r"))"
)
_GO = re.compile(r"^()(func\s+(?:\([^)]*\)\s*)?\w+\s*\([^)]*\)?|type\s+\w+\s+(?:struct|interface))")
_RUST = re.compile(
    r"^(\s*)((?:pub(?:\([^)]*\))?\s+)?(?:"
    r"(?:async\s+)?(?:unsafe\s+)?fn\s+\w+(?:<[^>]*>)?\s*\([^)]*\)?"
    r"|(?:struct|enum|trait|mod|type)\s+\w+"
    r")|impl(?:<[^>]*>)?\s+[^{]+)"
)
_JVM = re.compile(
    r"^(\s*)((?:(?:public|private|protected|internal|static|final|abstract|open|data|sealed|override|suspend)\s+)*"
    r"(?:(?:class|interface|enum|record|object|struct|protocol|extension)\s+\w+"
    r"|(?:fun|func)\s+(?:<[^>]*>\s*)?[\w.]+\s*\([^)]*\)?))"
)
_C = re.compile(
    r"^()((?:class|struct|enum|namespace)\s+\w+"
    r"|(?!(?:if|for|while|switch|return|else|typedef|do|case)\b)[A-Za-z_][\w\s\*&:<>,~]*?\b[\w:~]+\s*\([^;{}]*\)\s*(?:const\s*)?\{?\s*$)"
)
_RUBY = re.compile(r"^(\s*)((?:class|module|def)\s+[\w.:?!=]+(?:\s*\([^)]*\)?)?)")
_PHP = re.compile(
    r"^(\s*)((?:(?:public|private|protected|static|abstract|final)\s+)*"
    r"(?:function\s+\w+\s*\([^)]*\)?|(?:class|interface|trait)\s+\w+))"
)
_PY_FALLBACK = re.compile(r"^(\s*)((?:async\s+def|def|class)\s+\w+(?:\([^)]*\)?)?)")

_PATTERNS: dict[str, re.Pattern[str]] = {
    **dict.fromkeys((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"), _JS),
    ".go": _GO,
    ".rs": _RUST,
    **dict.fromkeys((".java", ".kt", ".kts", ".cs", ".swift", ".scala"), _JVM),
    **dict.fromkeys((".c", ".h", ".cc", ".cpp", ".hpp", ".cxx"), _C),
    ".rb": _RUBY,
    ".php": _PHP,
}
SOURCE_EXTS = {".py", *_PATTERNS}

# path -> (mtime_ns, size, symbols). Only changed files are re-parsed.
_cache: dict[str, tuple[int, int, list[Symbol]]] = {}
_CACHE_MAX = 5000


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_SIG_CHARS else text[: MAX_SIG_CHARS - 1] + "…"


def _python_symbols(source: str) -> list[Symbol]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return _regex_symbols(source, _PY_FALLBACK)

    def func(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return _clip(f"{prefix} {node.name}({ast.unparse(node.args)})")

    out: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((0, func(node)))
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            out.append((0, _clip(f"class {node.name}({bases})" if bases else f"class {node.name}")))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    not item.name.startswith("_") or item.name == "__init__"
                ):
                    out.append((1, func(item)))
    return out


def _regex_symbols(source: str, pattern: re.Pattern[str]) -> list[Symbol]:
    out: list[Symbol] = []
    for line in source.splitlines():
        if len(line) > 400:
            continue  # minified or generated
        m = pattern.match(line)
        if not m:
            continue
        indent = len(m.group(1).expandtabs(4))
        if indent > 8:
            continue  # deeper than a class member: local helpers, not structure
        out.append((0 if indent == 0 else 1, _clip(m.group(2).rstrip(" {"))))
    return out


def _symbols(path: Path) -> list[Symbol]:
    try:
        st = path.stat()
    except OSError:
        return []
    key = str(path)
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    symbols: list[Symbol] = []
    if st.st_size <= MAX_SOURCE_BYTES:
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            source = ""
        ext = path.suffix.lower()
        symbols = _python_symbols(source) if ext == ".py" else _regex_symbols(source, _PATTERNS[ext])
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[key] = (st.st_mtime_ns, st.st_size, symbols)
    return symbols


_TEST_HINT = re.compile(r"(^|/)(tests?|e2e|__tests__|spec)/|(^|/)test_[^/]*$|\.(test|spec)\.[^/]+$|(^|/)conftest\.py$")


def _block(rel: str, symbols: list[Symbol], detail: int) -> str:
    """detail 0: every symbol · 1: top-level symbols · 2: the path only."""
    if detail == 2:
        return rel
    shown = [s for s in symbols if detail == 0 or s[0] == 0]
    lines = [rel] + [f"{'  ' * (depth + 1)}{text}" for depth, text in shown[:MAX_SYMBOLS_PER_FILE]]
    if len(shown) > MAX_SYMBOLS_PER_FILE:
        lines.append(f"  … {len(shown) - MAX_SYMBOLS_PER_FILE} more")
    return "\n".join(lines)


_WORD = re.compile(r"[A-Za-z][a-z0-9]*|[A-Z]+(?![a-z])|[0-9]+")
_DECL_NAME = re.compile(
    r"\b(?:def|class|function|fn|func|interface|type|struct|enum|const|let|var|trait|impl|module|object)\s+\*?\s*([A-Za-z_]\w*)"
)
_STOP = {
    "the", "and", "for", "with", "this", "that", "from", "into", "file", "files", "code", "make",
    "add", "fix", "use", "get", "set", "new", "can", "you", "please", "should", "would", "what",
    "how", "why", "where", "when", "does", "not", "but", "all", "are", "was", "has", "have",
    "def", "class", "function", "test", "tests", "src", "app", "lib", "index", "main", "init",
}


def _words(text: str) -> set[str]:
    """Lower-cased identifier parts: `loadConfig`, `load_config` and
    `load-config` all give {"load", "config"}."""
    out = set()
    for raw in re.split(r"[^A-Za-z0-9]+", text or ""):
        for w in _WORD.findall(raw):
            w = w.lower()
            if len(w) >= 3 and w not in _STOP:
                out.add(w)
    return out


def _score(rel: str, symbols: list[Symbol], mtime: float, query: set[str], now: float) -> float:
    """Higher = more worth showing. Without a query this reproduces the old
    order (application code before tests, shallow before deep)."""
    score = -0.5 * rel.count("/") - (3.0 if _TEST_HINT.search(rel) else 0.0)
    if query:
        path_hits = len(query & _words(rel))
        names = {n for _, text in symbols for n in _DECL_NAME.findall(text)}
        name_hits = len(query & _words(" ".join(names)))
        score += 4.0 * path_hits + 2.0 * min(name_hits, 5)
    age = now - mtime
    if age < 3600:
        score += 3.0
    elif age < 86400:
        score += 1.5
    return score


def build(workdir: str, max_chars: int = 4000, query: str = "") -> str:
    """Outline of the source files under `workdir`, at most `max_chars`
    long. Empty string when there's nothing to map.

    Files are ranked by how well their path and the names they define
    match `query` (the user's request), plus a boost for recently edited
    files; application code ranks above tests. The budget is spent in rank
    order: the best files get their functions and classes listed, then
    lesser ones get just their path, and the rest are counted. The result
    is listed in path order so it reads like a tree."""
    import time

    root = Path(workdir)
    if not root.is_dir():
        return ""
    found: list[tuple[str, list[Symbol], float]] = []
    skipped = 0
    for path, rel in code_search._walk(root):
        if path.suffix.lower() not in SOURCE_EXTS:
            continue
        if len(found) >= MAX_MAP_FILES:
            skipped += 1
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        found.append((rel, _symbols(path), mtime))
    if not found:
        return ""
    q = _words(query)
    now = time.time()
    ranked = sorted(found, key=lambda f: (-_score(f[0], f[1], f[2], q, now), f[0]))

    more = "\n… {n} more source files not listed; use glob to find them."
    budget = max_chars - (len(more) + 6)
    chosen: dict[str, str] = {}
    used = 0
    paths_cost = sum(len(rel) + 1 for rel, _, _ in found)
    if paths_cost <= 0.6 * budget:
        # Small project: list every file, then add symbols in rank order.
        for rel, _, _ in found:
            chosen[rel] = rel
        used = paths_cost
        for rel, symbols, _ in ranked:
            better = _block(rel, symbols, 1)
            extra = len(better) - len(rel)
            if extra > 0 and used + extra <= budget:
                chosen[rel] = better
                used += extra
    else:
        # Big project: in rank order, a file with its top-level symbols if
        # that fits, else just its path, until the budget runs out.
        for rel, symbols, _ in ranked:
            full = _block(rel, symbols, 1)
            if used + len(full) + 1 <= budget:
                chosen[rel] = full
                used += len(full) + 1
            elif used + len(rel) + 1 <= budget:
                chosen[rel] = rel
                used += len(rel) + 1
    # Pass 2: methods too, for the best files, while there's room.
    for rel, symbols, _ in ranked:
        if rel not in chosen:
            continue
        better = _block(rel, symbols, 0)
        extra = len(better) - len(chosen[rel])
        if extra > 0 and used + extra <= budget:
            chosen[rel] = better
            used += extra
    text = "\n".join(chosen[rel] for rel in sorted(chosen, key=lambda r: (r.count("/"), r)))
    left = len(found) - len(chosen) + skipped
    return text + more.format(n=left) if left else text
