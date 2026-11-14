"""Structured git and GitHub operations for the workspace's Changes tab.

These back direct clicks in the UI (stage, commit, push, open a PR), so
they're not approval-gated like agent tool calls. Everything runs through
argv lists (no shell), paths are passed after `--`, and git/gh are told
never to prompt, so a missing credential fails fast instead of hanging.

GitHub features use the `gh` CLI with whatever account it's logged into;
Zenith stores no GitHub token of its own.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_COAUTHOR_RE = re.compile(r"^\s*co-authored-by:.*$", re.IGNORECASE | re.MULTILINE)
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")

_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "never",
    "GH_PROMPT_DISABLED": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "NO_COLOR": "1",
}


class GitError(RuntimeError):
    pass


@dataclass
class Result:
    code: int
    out: str
    err: str


async def _exec(argv: list[str], cwd: Path, timeout: float = 20, env: dict | None = None) -> Result:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), env=env or _ENV,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise GitError(f"`{argv[0]}` isn't installed.") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise GitError(f"`{' '.join(argv[:3])}` took longer than {int(timeout)}s.") from exc
    return Result(proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))


async def _git(root: Path, *args: str, timeout: float = 20, ok: tuple[int, ...] = (0,)) -> str:
    r = await _exec(["git", *args], root, timeout)
    if r.code not in ok:
        raise GitError((r.err or r.out).strip() or f"git {args[0]} failed ({r.code}).")
    return r.out


def _check_paths(root: Path, paths: list[str]) -> list[str]:
    clean = []
    real_root = root.resolve()
    for p in paths:
        if not p or p.startswith("-"):
            raise GitError(f"Bad path: {p!r}")
        full = (real_root / p).resolve()
        if full != real_root and real_root not in full.parents:
            raise GitError(f"Path is outside the working folder: {p}")
        clean.append(p)
    return clean


# --- status ---------------------------------------------------------------

_STATUS_WORD = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied",
                "U": "conflict", "T": "modified", "?": "untracked", "!": "ignored"}


async def status(root: Path) -> dict:
    """Branch, upstream, ahead/behind, and changed files split into staged
    and unstaged. `is_repo` False (and nothing else) outside a repository."""
    r = await _exec(["git", "rev-parse", "--is-inside-work-tree"], root, 10)
    if r.code != 0 or r.out.strip() != "true":
        return {"is_repo": False}
    raw = await _git(root, "status", "--porcelain=v1", "-z", "--branch", "--untracked-files=all")
    parts = raw.split("\0")
    head = parts[0][3:] if parts and parts[0].startswith("## ") else ""
    branch, upstream, ahead, behind = head, None, 0, 0
    m = re.match(r"^(?:No commits yet on )?(.+?)(?:\.\.\.(\S+))?(?: \[(.*)\])?$", head)
    if m:
        branch, upstream = m.group(1), m.group(2)
        for kind, n in re.findall(r"(ahead|behind) (\d+)", m.group(3) or ""):
            if kind == "ahead":
                ahead = int(n)
            else:
                behind = int(n)
    staged, unstaged = [], []
    i = 1
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        orig = None
        if x in "RC":
            orig = parts[i] if i < len(parts) else None
            i += 1
        if x == "?" and y == "?":
            unstaged.append({"path": path, "status": "untracked"})
            continue
        if x == "!":
            continue
        if x == "U" or y == "U" or (x == y and x in "AD"):
            unstaged.append({"path": path, "status": "conflict"})
            continue
        if x != " ":
            staged.append({"path": path, "status": _STATUS_WORD.get(x, "modified"), **({"from": orig} if orig else {})})
        if y != " ":
            unstaged.append({"path": path, "status": _STATUS_WORD.get(y, "modified")})
    remote = (await _exec(["git", "remote", "get-url", "origin"], root, 10)).out.strip() or None
    return {
        "is_repo": True,
        "branch": branch,
        "detached": branch.startswith("HEAD"),
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "unstaged": unstaged,
        "remote": remote,
        "github": bool(remote and "github.com" in remote),
    }


async def diff(root: Path, path: str, staged: bool = False, max_chars: int = 200_000) -> str:
    [path] = _check_paths(root, [path])
    tracked = (await _exec(["git", "ls-files", "--error-unmatch", "--", path], root, 10)).code == 0
    if not tracked and not staged:
        # Untracked file: show it as all-added. --no-index exits 1 when files differ.
        out = await _git(root, "diff", "--no-color", "--no-index", "--", os.devnull, path, ok=(0, 1))
    else:
        args = ["diff", "--no-color"] + (["--staged"] if staged else []) + ["--", path]
        out = await _git(root, *args)
    return out[:max_chars]


# --- changing the index / history -----------------------------------------

async def stage(root: Path, paths: list[str]) -> None:
    await _git(root, "add", "-A", "--", *_check_paths(root, paths))


async def unstage(root: Path, paths: list[str]) -> None:
    paths = _check_paths(root, paths)
    has_head = (await _exec(["git", "rev-parse", "--verify", "-q", "HEAD"], root, 10)).code == 0
    if has_head:
        await _git(root, "restore", "--staged", "--", *paths)
    else:
        await _git(root, "rm", "-q", "--cached", "-r", "--", *paths)


async def commit(root: Path, message: str) -> str:
    message = _COAUTHOR_RE.sub("", message or "").strip()
    if not message:
        raise GitError("Write a commit message first.")
    staged = await _git(root, "diff", "--cached", "--name-only")
    if not staged.strip():
        raise GitError("Nothing is staged. Stage the files you want in this commit first.")
    await _git(root, "commit", "-q", "-m", message)
    return (await _git(root, "log", "-1", "--format=%h %s")).strip()


async def log(root: Path, count: int = 20) -> list[dict]:
    has_head = (await _exec(["git", "rev-parse", "--verify", "-q", "HEAD"], root, 10)).code == 0
    if not has_head:
        return []
    out = await _git(root, "log", f"-{max(1, min(count, 100))}", "--format=%h%x1f%s%x1f%an%x1f%cr%x1e")
    rows = []
    for rec in out.split("\x1e"):
        f = rec.strip().split("\x1f")
        if len(f) == 4:
            rows.append({"sha": f[0], "subject": f[1], "author": f[2], "when": f[3]})
    return rows


async def branches(root: Path) -> dict:
    out = await _git(root, "branch", "--format=%(refname:short)%09%(HEAD)")
    names, current = [], None
    for line in out.splitlines():
        name, _, mark = line.partition("\t")
        if name:
            names.append(name)
            if mark.strip() == "*":
                current = name
    return {"current": current, "branches": names}


async def switch_branch(root: Path, name: str, create: bool = False) -> None:
    if not _BRANCH_RE.match(name or "") or name.startswith("-") or ".." in name:
        raise GitError("That isn't a valid branch name.")
    await _git(root, "switch", *(["-c"] if create else []), name)


async def push(root: Path) -> str:
    st = await status(root)
    if not st.get("is_repo"):
        raise GitError("Not a git repository.")
    if not st.get("remote"):
        raise GitError("This repository has no `origin` remote to push to.")
    if st.get("detached"):
        raise GitError("You're not on a branch (detached HEAD).")
    args = ["push"] if st.get("upstream") else ["push", "-u", "origin", st["branch"]]
    r = await _exec(["git", *args], root, 90)
    if r.code != 0:
        raise GitError((r.err or r.out).strip() or "git push failed.")
    return (r.err or r.out).strip()


# --- GitHub (gh CLI) ------------------------------------------------------

def gh_installed() -> bool:
    return shutil.which("gh") is not None


async def _gh(root: Path, *args: str, timeout: float = 30) -> str:
    if not gh_installed():
        raise GitError("GitHub features need the GitHub CLI (`gh`). Install it and run `gh auth login`.")
    r = await _exec(["gh", *args], root, timeout)
    if r.code != 0:
        msg = (r.err or r.out).strip()
        if "auth login" in msg or "not logged" in msg.lower():
            msg = "The GitHub CLI isn't logged in. Run `gh auth login` in the terminal."
        raise GitError(msg or f"gh {args[0]} failed.")
    return r.out


async def gh_status(root: Path) -> dict:
    if not gh_installed():
        return {"installed": False, "logged_in": False}
    r = await _exec(["gh", "auth", "status"], root, 15)
    return {"installed": True, "logged_in": r.code == 0}


async def issues(root: Path, limit: int = 30) -> list[dict]:
    out = await _gh(root, "issue", "list", "--state", "open", "--limit", str(limit),
                    "--json", "number,title,url,labels,updatedAt")
    return json.loads(out or "[]")


async def issue(root: Path, number: int) -> dict:
    out = await _gh(root, "issue", "view", str(int(number)), "--json", "number,title,body,url,labels,comments")
    return json.loads(out or "{}")


async def pulls(root: Path, limit: int = 30) -> list[dict]:
    out = await _gh(root, "pr", "list", "--state", "open", "--limit", str(limit),
                    "--json", "number,title,url,headRefName,isDraft,updatedAt")
    return json.loads(out or "[]")


async def create_pr(root: Path, title: str, body: str = "", base: str = "", draft: bool = False) -> str:
    title = (title or "").strip()
    if not title:
        raise GitError("The pull request needs a title.")
    body = _COAUTHOR_RE.sub("", body or "").strip()
    st = await status(root)
    if st.get("ahead") or not st.get("upstream"):
        await push(root)
    args = ["pr", "create", "--title", title, "--body", body or " "]
    if base:
        if not _BRANCH_RE.match(base):
            raise GitError("That isn't a valid base branch.")
        args += ["--base", base]
    if draft:
        args.append("--draft")
    out = await _gh(root, *args, timeout=60)
    urls = re.findall(r"https://github\.com/\S+/pull/\d+", out)
    return urls[-1] if urls else out.strip()


# --- agent commits (optional: one commit per approved edit) ---------------

_PROTECTED = {"main", "master", "trunk", "develop"}


def _slug(text: str, limit: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (s[:limit].rstrip("-") or "change")


async def agent_commit(root: Path, path: str, tool: str, request: str, run_id: str) -> dict:
    """Commit one file the agent just changed, on a work branch.

    On a main-like branch, first switches to `zenith/<request-slug>-<id>`
    (uncommitted work comes along, nothing is lost). Only `path` is
    committed (`git commit -- path`), so other files you have changed or
    staged stay out of the agent's commits. Returns {"branch", "commit",
    "switched"}; raises GitError if the folder isn't a repo or git fails."""
    st = await status(root)
    if not st.get("is_repo"):
        raise GitError("not a git repository")
    if st.get("detached"):
        raise GitError("detached HEAD; not committing")
    [path] = _check_paths(root, [path])
    switched = False
    branch = st["branch"]
    if branch in _PROTECTED:
        branch = f"zenith/{_slug(request)}-{run_id[:6]}"
        await _git(root, "switch", "-c", branch)
        switched = True
    await _git(root, "add", "-A", "--", path)
    if not (await _git(root, "diff", "--cached", "--name-only", "--", path)).strip():
        return {"branch": branch, "commit": None, "switched": switched}
    first = (request or "").strip().splitlines()[0][:72] if (request or "").strip() else ""
    subject = f"agent: {'create' if tool == 'write_file' else 'edit'} {path}"
    message = subject + (f"\n\nRequest: {first}" if first else "")
    await _git(root, "commit", "-q", "-m", message, "--", path)
    return {"branch": branch, "commit": (await _git(root, "log", "-1", "--format=%h")).strip(), "switched": switched}


# --- worktrees: a separate checkout for a task ------------------------------

async def _toplevel(root: Path) -> Path:
    return Path((await _git(root, "rev-parse", "--show-toplevel")).strip())


async def create_worktree(root: Path, name: str) -> dict:
    """New branch `zenith/<name>` from the current commit, checked out in a
    sibling folder `<repo>.zenith/<name>`, so work there never touches the
    main checkout. Returns {"path", "branch"}."""
    st = await status(root)
    if not st.get("is_repo"):
        raise GitError("This folder isn't a git repository.")
    if (await _exec(["git", "rev-parse", "--verify", "-q", "HEAD"], root, 10)).code != 0:
        raise GitError("Make a first commit before creating a separate copy.")
    slug = _slug(name, 40)
    top = await _toplevel(root)
    base = top.parent / f"{top.name}.zenith"
    path = base / slug
    n = 2
    while path.exists():
        path = base / f"{slug}-{n}"
        n += 1
    branch = f"zenith/{path.name}"
    if (await _exec(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], root, 10)).code == 0:
        raise GitError(f"A branch named {branch} already exists.")
    base.mkdir(parents=True, exist_ok=True)
    await _git(root, "worktree", "add", "-q", "-b", branch, str(path), timeout=60)
    return {"path": str(path), "branch": branch}


async def list_worktrees(root: Path) -> list[dict]:
    out = await _git(root, "worktree", "list", "--porcelain")
    items: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                items.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur["path"] = val
        elif key == "branch":
            cur["branch"] = val.removeprefix("refs/heads/")
    # The first entry is always the main checkout: never offered as a "copy".
    top = str(await _toplevel(root))
    return [w for w in items[1:] if w.get("path") != top]


async def remove_worktree(root: Path, path: str) -> None:
    known = {w["path"] for w in await list_worktrees(root)}
    if path not in known:
        raise GitError("That isn't one of this repository's separate copies.")
    r = await _exec(["git", "worktree", "remove", path], root, 60)
    if r.code != 0:
        msg = (r.err or r.out).strip()
        if "modified or untracked" in msg or "is dirty" in msg:
            msg = "That copy has uncommitted changes. Commit or discard them first."
        raise GitError(msg or "Couldn't remove the copy.")
