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


def build(workdir: str, max_chars: int = 4000) -> str:
    """Outline of the source files under `workdir`, at most `max_chars`
    long. Empty string when there's nothing to map."""
    root = Path(workdir)
    if not root.is_dir():
        return ""
    files: list[tuple[str, list[Symbol]]] = []
    skipped = 0
    for path, rel in code_search._walk(root):
        if path.suffix.lower() not in SOURCE_EXTS:
            continue
        if len(files) >= MAX_MAP_FILES:
            skipped += 1
            continue
        files.append((rel, _symbols(path)))
    if not files:
        return ""
    # Priority order: application code before tests, shallow before deep.
    # Entry points and top-level modules say the most about a project, and
    # this is the order in which files get detail (or survive truncation).
    files.sort(key=lambda f: (bool(_TEST_HINT.search(f[0])), f[0].count("/"), f[0]))

    more = "\n… {n} more source files not listed; use glob to find them."
    budget = max_chars - (len(more) + 6 if skipped else 0)
    blocks = [rel for rel, _ in files]
    used = sum(len(b) + 1 for b in blocks)
    if used > budget:
        # Even bare paths don't fit: list as many as do.
        kept: list[str] = []
        used = 0
        for rel in blocks:
            if used + len(rel) + 1 > max_chars - len(more) - 6:
                break
            kept.append(rel)
            used += len(rel) + 1
        return "\n".join(kept) + more.format(n=len(files) - len(kept) + skipped)
    # Spend what's left on symbols, in priority order: top-level symbols for
    # as many files as fit, then nested ones (methods).
    for detail in (1, 0):
        for i, (rel, symbols) in enumerate(files):
            better = _block(rel, symbols, detail)
            extra = len(better) - len(blocks[i])
            if extra > 0 and used + extra <= budget:
                blocks[i] = better
                used += extra
    text = "\n".join(blocks)
    return text + more.format(n=skipped) if skipped else text
