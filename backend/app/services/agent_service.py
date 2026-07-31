"""Agentic tool use: a ReAct-style loop that lets the model run shell
commands, read/write files, and search/fetch the web across multiple
steps instead of a single retrieve-then-answer turn.

Design choices, and why:

- **JSON-in-text tool calling, not Ollama's native `tools` API.** Native
  function calling only works on a subset of models (recent Llama/Qwen/
  Mistral builds); Cortex's whole pitch is "works with whatever you've
  pulled." Prompting the model to emit a strict JSON object and parsing
  it works with any chat model, at the cost of losing token-level
  streaming during the loop (each round is a full non-streaming call;
  only the final answer is pseudo-streamed to the UI).

- **Every tool call is audited** in the `tool_calls` table — nothing the
  agent does is invisible, regardless of autonomy mode.

- **Autonomy has three modes** (`agent_mode` config, settable from
  Settings, same idea as Cursor/Claude Code's confirm/auto-accept
  toggle):
    - "manual": every tool call pauses for your approval.
    - "semi":   read-only calls (read_file/list_dir/web/most bash) run
      immediately; anything that writes/deletes/executes ambiguously
      still pauses.
    - "full":   nothing pauses. Fast, and only as safe as your prompts.

- **No filesystem sandbox** — by explicit choice, tools operate on
  whatever filesystem the backend process can see (inside the Docker
  container by default; the real host only if you've added a bind
  mount in docker-compose.yml — see the commented block there). This
  is a deliberate "no guardrails, it's your machine" posture, not an
  oversight.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import re
import time
import uuid
from typing import Any, AsyncIterator

from app.core.config import settings
from app.core.logging import get_logger
from app.db.storage import _conn
from app.services.ollama_client import OllamaClient, OllamaError
from app.services.router import ModelRouter, RouteDecision

log = get_logger(__name__)

MAX_ARG_LOG_CHARS = 2000

TOOLS: dict[str, dict[str, str]] = {
    "bash": {"description": "Run a shell command. Args: command (string), cwd (string, optional)."},
    "read_file": {"description": "Read a text file. Args: path (string)."},
    "write_file": {
        "description": "Write or append text to a file, creating parent dirs as needed. Use this "
                        "for new files or full rewrites; for changing part of an existing file, use "
                        "edit_file instead — it's safer and doesn't require reproducing the whole file. "
                        "Args: path (string), content (string), mode ('overwrite'|'append', default 'overwrite')."
    },
    "edit_file": {
        "description": "Make a precise change to an existing file: replace one exact occurrence of "
                        "old_string with new_string, leaving the rest of the file untouched. Prefer "
                        "this over write_file for editing code — include enough surrounding context "
                        "in old_string to make it uniquely identify one spot. Fails if old_string "
                        "isn't found, or is found more than once. Args: path (string), old_string "
                        "(string), new_string (string)."
    },
    "list_dir": {"description": "List a directory's contents. Args: path (string)."},
    "web_search": {"description": "Search the web. Args: query (string)."},
    "fetch_url": {"description": "Fetch and extract the readable text of a URL. Args: url (string)."},
    "shell_start": {
        "description": "Start a long-running background process (dev server, watch mode, REPL) that "
                        "keeps running across multiple tool calls — unlike `bash`, which waits for the "
                        "command to finish before returning. Returns a session_id. Use shell_output to "
                        "read what it has printed since your last check, shell_write_stdin to send it "
                        "input, and shell_kill to stop it when you're done. Args: command (string), "
                        "cwd (string, optional)."
    },
    "shell_output": {
        "description": "Read new output (stdout+stderr) from a shell_start session since the last time "
                        "you called this for it. Also reports whether it's still running. Args: "
                        "session_id (string)."
    },
    "shell_write_stdin": {
        "description": "Send a line of text to a running shell_start session's stdin — e.g. answering "
                        "a REPL prompt or typing a command into an interactive process. Args: "
                        "session_id (string), text (string)."
    },
    "shell_kill": {"description": "Stop a running shell_start session. Args: session_id (string)."},
    "shell_list": {"description": "List currently running shell_start sessions for this conversation. Args: (none)."},
    "spawn_subagent": {
        "description": "Delegate a self-contained task to a sub-agent that works autonomously — no "
                        "approval prompts, it can't ask you questions — and reports back a summary "
                        "when done. Useful for a separate investigation or chunk of work you'd "
                        "otherwise have to context-switch into yourself (e.g. 'research X' while you "
                        "keep working on Y). Give it a clear, standalone task description. It cannot "
                        "spawn further sub-agents. Args: task (string)."
    },
    "browser_navigate": {
        "description": "Open a URL in a real headless browser — unlike fetch_url, this renders "
                        "JavaScript, so it works on pages that need it (SPAs, login-gated content "
                        "rendered client-side, sites that block plain HTTP fetches). Starts a browser "
                        "session for this conversation if none is open yet; later browser_* calls act "
                        "on the same page. Returns the page title and visible text. Args: url (string)."
    },
    "browser_click": {
        "description": "Click an element on the currently open browser page (from browser_navigate). "
                        "Args: selector (string, CSS selector)."
    },
    "browser_type": {
        "description": "Type text into an input/textarea on the currently open browser page. Args: "
                        "selector (string, CSS selector), text (string), submit (boolean, optional — "
                        "if true, submits the enclosing form after typing)."
    },
    "browser_get_text": {
        "description": "Read the visible text of the currently open browser page, or of one element. "
                        "Args: selector (string, optional — omit for the whole page)."
    },
    "browser_close": {"description": "Close the browser session for this conversation. Args: (none)."},
    "run_checks": {
        "description": "Run the project's test/lint command and get back whether it passed or failed, "
                        "with the output. Use this to verify your changes actually work after editing "
                        "files, instead of guessing. Uses the configured check command by default "
                        "(set in Settings). Args: command (string, optional — override the configured "
                        "command for this run)."
    },
    "git": {
        "description": "Structured git operations in the conversation's working directory — cleaner "
                        "than raw `git` via bash, with parsed output. Args: op (one of 'status', "
                        "'diff', 'log', 'commit', 'branch'). For 'diff': path (string, optional), "
                        "staged (boolean, optional — show staged changes). For 'log': count (int, "
                        "optional, default 10). For 'commit': message (string, required), add_all "
                        "(boolean, optional, default true — stage everything first). For 'branch': "
                        "name (string, optional — create/switch to it; omit to list branches)."
    },
}

_SYSTEM_PROMPT_HEADER = """You are Cortex operating in agent mode: you can use tools across multiple
steps to satisfy the user's request, instead of answering from memory alone.

Available tools:
"""

_SYSTEM_PROMPT_FOOTER = """
Respond with EXACTLY ONE JSON object and nothing else — no prose, no markdown fence:
  To call a tool:      {"tool": "<name>", "args": {...}}
  To give a final answer: {"final": "<answer text, written for the user>"}

Rules:
- One tool call per turn. You will see its result before deciding the next step.
- Only use a tool when it actually helps; otherwise answer directly with {"final": ...}.
- Never invent a tool result — wait for the real one.
- Once you have enough information, stop and return {"final": ...}. Don't over-explore.
"""


def _build_system_prompt(mcp_tools: list[dict]) -> str:
    """Built per-turn rather than a module constant: MCP tools come from
    whatever servers are enabled right now, discovered fresh each turn
    since they can be added/removed from Settings between conversations."""
    lines = [f"- {name}: {spec['description']}" for name, spec in TOOLS.items()]
    lines += [f"- {t['agent_tool_name']}: {t['description']}" for t in mcp_tools]
    return _SYSTEM_PROMPT_HEADER + "\n".join(lines) + _SYSTEM_PROMPT_FOOTER

_SAFE_BASH_CMDS = {
    "ls", "cat", "pwd", "echo", "grep", "find", "head", "tail", "wc",
    "git", "which", "whoami", "date", "df", "du", "ps", "uname", "file",
    "stat", "tree", "env", "id", "hostname",
}
_UNSAFE_BASH_TOKENS = (">", ">>", "|", "&", ";", "`", "$(", "sudo", "rm ", "rm\t",
                       "mv ", "cp ", "chmod", "chown", "kill", "dd ", "mkfs",
                       "wget", "curl", ":(){", "shutdown", "reboot", "eval")


class AgentError(RuntimeError):
    pass


def _classify_bash_command(cmd: str) -> str:
    cmd = cmd.strip()
    first = cmd.split(" ", 1)[0] if cmd else ""
    if first in _SAFE_BASH_CMDS and not any(tok in cmd for tok in _UNSAFE_BASH_TOKENS):
        return "safe"
    return "risky"


def classify_risk(tool: str, args: dict[str, Any]) -> str:
    """Returns "safe" or "risky". Safe calls auto-run in "semi" mode;
    risky calls always pause for approval outside "full" mode."""
    if tool in ("read_file", "list_dir", "web_search", "fetch_url", "shell_output", "shell_list", "shell_kill",
                "browser_get_text", "browser_close"):
        return "safe"
    if tool in ("write_file", "edit_file", "shell_write_stdin", "browser_navigate", "browser_click", "browser_type"):
        # Navigating/clicking/typing can trigger real side effects (form
        # submissions, purchases, account actions) — same caution as a
        # file write, not treated as merely "reading a page."
        return "risky"
    if tool == "bash":
        return _classify_bash_command(str(args.get("command", "")))
    if tool == "shell_start":
        # Starting a background process is at least as consequential as
        # running the same command with `bash` — same classification.
        return _classify_bash_command(str(args.get("command", "")))
    if tool == "spawn_subagent":
        # Always risky: it's one approval that authorizes a whole
        # unattended sub-loop, not a single action — the sub-agent's own
        # tool calls don't get individually gated after this.
        return "risky"
    if tool == "git":
        # Read-only inspection is safe; anything that writes repo state
        # (commit, creating/switching a branch) pauses like a file write.
        op = str(args.get("op", "")).strip()
        return "safe" if op in ("status", "diff", "log") else "risky"
    if tool == "run_checks":
        # Running the user-configured check command is safe (they chose it);
        # an arbitrary command override the model supplies is not.
        return "risky" if str(args.get("command", "")).strip() else "safe"
    return "risky"  # unknown tool — err conservative


# --- Pending-approval registry -------------------------------------------
# In-memory (single backend process, matches conversation_lock's pattern).
# Keyed by tool_call id; approve_tool_call() from the API layer resolves it.
_pending: dict[str, asyncio.Future] = {}


def approve_tool_call(call_id: str, approved: bool) -> bool:
    fut = _pending.get(call_id)
    if fut is None or fut.done():
        return False
    fut.set_result(approved)
    return True


async def _await_approval(call_id: str, timeout: float) -> bool:
    fut = asyncio.get_event_loop().create_future()
    _pending[call_id] = fut
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return False
    finally:
        _pending.pop(call_id, None)


# --- Tool call audit trail -------------------------------------------------

def _log_call(
    conversation_id: str, tool: str, args: dict, risk: str,
    diff: str | None = None, previous_content: str | None = None,
    had_previous_file: bool | None = None, run_id: str | None = None,
) -> str:
    call_id = str(uuid.uuid4())
    with _conn() as conn:
        conn.execute(
            """INSERT INTO tool_calls
               (id, conversation_id, tool, args, risk, status, created_at,
                diff, previous_content, had_previous_file, run_id)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)""",
            (call_id, conversation_id, tool, json.dumps(args)[:MAX_ARG_LOG_CHARS], risk, time.time(),
             diff, previous_content,
             None if had_previous_file is None else int(had_previous_file), run_id),
        )
    return call_id


def _resolve_call(call_id: str, status: str, result: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE tool_calls SET status = ?, result = ?, resolved_at = ? WHERE id = ?",
            (status, (result or "")[:MAX_ARG_LOG_CHARS] if result else result, time.time(), call_id),
        )


def list_tool_calls(conversation_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tool_calls WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def revert_tool_call(call_id: str) -> str:
    """Undo an already-executed edit_file/write_file call by restoring the
    file to what `previous_content`/`had_previous_file` recorded before the
    edit ran — or deleting the file if the edit created it. Same one-step
    undo model as an editor's Cmd+Z, scoped to a single tool call."""
    from pathlib import Path
    from app.db import storage

    with _conn() as conn:
        row = conn.execute("SELECT * FROM tool_calls WHERE id = ?", (call_id,)).fetchone()
    if row is None:
        raise AgentError("No tool call with that id.")
    call = dict(row)
    if call["tool"] not in ("edit_file", "write_file"):
        raise AgentError("Only file edits can be reverted.")
    if call["status"] != "executed":
        raise AgentError("This call hasn't run (or was already reverted/denied) — nothing to revert.")
    if call["had_previous_file"] is None:
        raise AgentError("No backup was recorded for this edit — it predates the revert feature.")

    args = json.loads(call["args"])
    path = args.get("path")
    if not path:
        raise AgentError("No path recorded for this call.")
    workdir = storage.get_conversation_workdir(call["conversation_id"])
    p = _resolve_path(path, workdir)

    try:
        if call["had_previous_file"]:
            p.write_text(call["previous_content"] or "")
            msg = f"Reverted {path} to its previous contents."
        else:
            if p.exists():
                p.unlink()
            msg = f"Reverted {path} by deleting it (it didn't exist before this edit)."
    except Exception as exc:
        raise AgentError(f"Revert failed: {exc}") from exc

    with _conn() as conn:
        conn.execute("UPDATE tool_calls SET status = 'reverted' WHERE id = ?", (call_id,))
    return msg


def list_runs(conversation_id: str) -> list[dict]:
    """Groups this conversation's tool calls by run_id (one agent turn) so
    the UI can offer 'undo this whole run' instead of only one file at a
    time. Runs with no revertible edits are omitted."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT run_id, MIN(created_at) AS started_at, COUNT(*) AS call_count,
                      SUM(CASE WHEN tool IN ('edit_file','write_file') AND status = 'executed' THEN 1 ELSE 0 END) AS revertible_count
               FROM tool_calls
               WHERE conversation_id = ? AND run_id IS NOT NULL
               GROUP BY run_id
               ORDER BY started_at DESC""",
            (conversation_id,),
        ).fetchall()
    return [dict(r) for r in rows if r["revertible_count"] > 0]


def revert_run(run_id: str) -> list[str]:
    """Undoes every file edit made during one agent run, most-recent-first
    — so if step 3 depended on step 2's edit, unwinding in reverse order
    restores each file to what it looked like right before this run
    touched it, same end state as if the run never happened."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT id FROM tool_calls
               WHERE run_id = ? AND tool IN ('edit_file','write_file') AND status = 'executed'
               ORDER BY created_at DESC""",
            (run_id,),
        ).fetchall()
    messages = []
    for row in rows:
        try:
            messages.append(revert_tool_call(row["id"]))
        except AgentError as exc:
            messages.append(f"Skipped: {exc}")
    return messages


def _preview_diff(tool: str, args: dict, workdir: str | None) -> tuple[str | None, str | None, bool | None]:
    """Computed before approval/execution so both the approval prompt and
    the audit trail show the real before/after — not just raw JSON args.
    Returns (unified_diff_or_none, previous_content_or_none, had_previous_file_or_none).
    Best-effort: any failure here just means no preview, execution still
    runs its own validation and reports its own error."""
    if tool not in ("edit_file", "write_file"):
        return None, None, None
    path = args.get("path")
    if not path:
        return None, None, None
    try:
        p = _resolve_path(path, workdir)
    except Exception:
        return None, None, None

    had_previous_file = p.exists() and p.is_file()
    previous_content = None
    if had_previous_file:
        try:
            previous_content = p.read_text()
        except Exception:
            return None, None, None

    if tool == "edit_file":
        old_string = args.get("old_string")
        new_string = args.get("new_string", "")
        if not had_previous_file or old_string is None or previous_content.count(old_string) != 1:
            return None, previous_content, had_previous_file
        new_content = previous_content.replace(old_string, new_string, 1)
    else:  # write_file
        if args.get("mode") == "append":
            new_content = (previous_content or "") + args.get("content", "")
        else:
            new_content = args.get("content", "")

    old_lines = (previous_content or "").splitlines()
    new_lines = new_content.splitlines()
    diff = "\n".join(difflib.unified_diff(old_lines, new_lines, fromfile=path, tofile=path, lineterm=""))
    return (diff or None), previous_content, had_previous_file


# --- Tool execution ---------------------------------------------------------

def _resolve_path(path: str, workdir: str | None):
    """Relative paths resolve against the conversation's bound working
    directory (if any) — the same "you never repeat the full path"
    convenience Claude Code gets from binding to a repo. Absolute paths
    always pass through untouched."""
    from pathlib import Path

    p = Path(path)
    if p.is_absolute() or not workdir:
        return p
    return Path(workdir) / p


async def _run_bash(args: dict, timeout: float, max_chars: int, workdir: str | None = None) -> str:
    command = str(args.get("command", "")).strip()
    cwd = args.get("cwd") or workdir or None
    if not command:
        return "Error: no command given."
    try:
        proc = await asyncio.create_subprocess_shell(
            command, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Error: command timed out after {timeout}s."
        out = stdout.decode(errors="ignore")
        err = stderr.decode(errors="ignore")
        parts = [f"exit_code: {proc.returncode}"]
        if out.strip():
            parts.append(f"stdout:\n{out}")
        if err.strip():
            parts.append(f"stderr:\n{err}")
        return "\n".join(parts)[:max_chars]
    except Exception as exc:
        return f"Error running command: {exc}"


_COAUTHOR_RE = re.compile(r"(?im)^\s*co-authored-by:.*$")


async def _git_exec(argv: list[str], cwd: str, timeout: float) -> tuple[int, str, str]:
    """argv-based (no shell) so a commit message can't be shell-injected."""
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", f"git timed out after {timeout}s."
    return proc.returncode, stdout.decode(errors="ignore"), stderr.decode(errors="ignore")


async def _run_git(args: dict, timeout: float, max_chars: int, workdir: str | None = None) -> str:
    op = str(args.get("op", "")).strip()
    cwd = workdir or None
    if not cwd:
        return ("Error: the git tool needs a working directory bound to this conversation — "
                "set one with the folder picker in the header first.")

    if op == "status":
        argv = ["git", "status", "--short", "--branch"]
    elif op == "log":
        try:
            count = max(1, min(int(args.get("count", 10)), 100))
        except (TypeError, ValueError):
            count = 10
        argv = ["git", "log", f"-{count}", "--oneline", "--decorate"]
    elif op == "diff":
        argv = ["git", "diff"]
        if args.get("staged"):
            argv.append("--staged")
        if args.get("path"):
            argv += ["--", str(args["path"])]
    elif op == "commit":
        message = str(args.get("message", "")).strip()
        if not message:
            return "Error: commit needs a message."
        # Honor the repo owner's standing rule: never let an agent-authored
        # commit carry a Co-Authored-By trailer (the model sometimes adds
        # one unprompted). Strip any such line before committing.
        message = _COAUTHOR_RE.sub("", message).strip()
        if args.get("add_all", True):
            code, _, err = await _git_exec(["git", "add", "-A"], cwd, timeout)
            if code != 0:
                return f"Error staging changes: {err.strip() or code}"
        argv = ["git", "commit", "-m", message]
    elif op == "branch":
        name = args.get("name")
        if name:
            # Create+switch; if it already exists, just switch to it.
            code, out, err = await _git_exec(["git", "switch", "-c", str(name)], cwd, timeout)
            if code != 0 and "already exists" in err:
                code, out, err = await _git_exec(["git", "switch", str(name)], cwd, timeout)
            combined = (out + err).strip() or f"(exit {code})"
            return combined[:max_chars]
        argv = ["git", "branch", "--list"]
    else:
        return f"Error: unknown git op {op!r}. Use one of: status, diff, log, commit, branch."

    code, out, err = await _git_exec(argv, cwd, timeout)
    body = out if out.strip() else err
    if code != 0 and not body.strip():
        body = f"(git exited {code})"
    if op == "status" and not body.strip():
        body = "(clean working tree)"
    return body[:max_chars]


async def _run_checks(args: dict, workdir: str | None = None) -> str:
    """Run the project's test/lint command and report pass/fail + output.
    Gives the model a first-class way to verify its edits instead of
    guessing whether they worked."""
    command = str(args.get("command", "")).strip() or str(settings.get("agent_check_command", "")).strip()
    if not command:
        return ("Error: no check command configured. Set one in Settings → Agent tools "
                "(e.g. 'pytest -q' or 'npm test'), or pass a command explicitly.")
    cwd = workdir or None
    timeout = float(settings.get("agent_check_timeout_seconds", 180))
    max_chars = int(settings.get("agent_output_max_chars", 4000))
    try:
        proc = await asyncio.create_subprocess_shell(
            command, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"Checks TIMED OUT after {timeout}s (command: {command})."
    except Exception as exc:
        return f"Error running checks: {exc}"
    verdict = "PASSED" if proc.returncode == 0 else "FAILED"
    output = out.decode(errors="ignore")
    # For a passing run the tail is what matters (summary line); for a
    # failing one the model needs to see the failure, which tools also
    # print near the end — so keep the tail either way.
    if len(output) > max_chars:
        output = "…(truncated)…\n" + output[-max_chars:]
    return f"Checks {verdict} (exit {proc.returncode}, command: {command}).\n{output}".rstrip()


# --- Persistent shell sessions ---------------------------------------------
# In-memory, module-level — same "single backend process" assumption as the
# _pending approval registry above. A session outlives the tool call that
# started it (that's the whole point: `bash` blocks until the command
# exits, this doesn't), so it can't live in the DB-backed tool_calls audit
# row the way one-shot results do; it has to live as long as the process
# does, which in practice means "until the backend restarts or it's killed."
_MAX_SESSIONS = 8
_SESSION_BUFFER_CAP = 200_000  # chars kept per session; oldest trimmed first

_shell_sessions: dict[str, dict[str, Any]] = {}


async def _pump_session_output(session: dict) -> None:
    """Background task: continuously drains the process's stdout (stderr
    merged in) into the session's buffer so output isn't lost between the
    model's shell_output polls, and isn't blocked waiting for a read."""
    proc = session["proc"]
    try:
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            text = chunk.decode(errors="ignore")
            session["buffer"] += text
            if len(session["buffer"]) > _SESSION_BUFFER_CAP:
                overflow = len(session["buffer"]) - _SESSION_BUFFER_CAP
                session["buffer"] = session["buffer"][overflow:]
                session["last_sent"] = max(0, session["last_sent"] - overflow)
    except Exception:
        pass
    finally:
        session["alive"] = False
        if proc.returncode is not None:
            session["exit_code"] = proc.returncode
        else:
            # proc.wait() has been observed to hang indefinitely in some
            # container environments even after the stdout pipe hit EOF
            # (a child-watcher quirk, not a real still-running process) —
            # never let that block forever.
            try:
                session["exit_code"] = await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                session["exit_code"] = proc.returncode  # best-effort; may stay None


async def _run_shell_start(args: dict, conversation_id: str, workdir: str | None = None) -> str:
    command = str(args.get("command", "")).strip()
    if not command:
        return "Error: no command given."
    live = sum(1 for s in _shell_sessions.values() if s["alive"])
    if live >= _MAX_SESSIONS:
        return f"Error: {_MAX_SESSIONS} shell sessions are already running — kill one with shell_kill first."
    cwd = args.get("cwd") or workdir or None
    try:
        proc = await asyncio.create_subprocess_shell(
            command, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.PIPE,
            start_new_session=True,  # own process group — see _run_shell_kill
        )
    except Exception as exc:
        return f"Error starting session: {exc}"

    session_id = str(uuid.uuid4())
    session = {
        "id": session_id, "conversation_id": conversation_id, "command": command,
        "cwd": cwd, "proc": proc, "buffer": "", "last_sent": 0,
        "alive": True, "exit_code": None, "created_at": time.time(),
    }
    _shell_sessions[session_id] = session
    session["reader_task"] = asyncio.create_task(_pump_session_output(session))

    # Grace period so the initial output (e.g. "Server running on :3000")
    # is already there for the model to see, without blocking indefinitely
    # on a process that's meant to keep running.
    await asyncio.sleep(1.0)
    output = session["buffer"]
    session["last_sent"] = len(session["buffer"])
    status = "running" if session["alive"] else f"exited (code {session['exit_code']})"
    return f"Started session {session_id} ({status}).\n{output}".rstrip()


def _get_session(session_id: str, conversation_id: str) -> dict | None:
    session = _shell_sessions.get(session_id)
    if session is None or session["conversation_id"] != conversation_id:
        return None
    return session


def _run_shell_output(args: dict, conversation_id: str) -> str:
    session_id = str(args.get("session_id", ""))
    session = _get_session(session_id, conversation_id)
    if session is None:
        return "Error: no session with that id in this conversation."
    new_output = session["buffer"][session["last_sent"]:]
    session["last_sent"] = len(session["buffer"])
    status = "running" if session["alive"] else f"exited (code {session['exit_code']})"
    return f"Session {session_id}: {status}.\n{new_output}" if new_output else f"Session {session_id}: {status}. (no new output)"


async def _run_shell_write_stdin(args: dict, conversation_id: str) -> str:
    session_id = str(args.get("session_id", ""))
    text = str(args.get("text", ""))
    session = _get_session(session_id, conversation_id)
    if session is None:
        return "Error: no session with that id in this conversation."
    if not session["alive"]:
        return f"Error: session {session_id} has already exited."
    try:
        session["proc"].stdin.write((text + "\n").encode())
        await session["proc"].stdin.drain()
        return f"Sent to session {session_id}."
    except Exception as exc:
        return f"Error writing to session: {exc}"


async def _run_shell_kill(args: dict, conversation_id: str) -> str:
    session_id = str(args.get("session_id", ""))
    session = _get_session(session_id, conversation_id)
    if session is None:
        return "Error: no session with that id in this conversation."
    if not session["alive"]:
        return f"Session {session_id} had already exited (code {session['exit_code']})."
    try:
        # `sh -c "<command>"` leaves any grandchild the command spawns
        # (e.g. the real `sleep`/`node`/etc process under the shell)
        # holding the stdout pipe open even after the shell itself is
        # killed — so plain proc.kill() only kills the shell, and
        # _pump_session_output's read() then blocks forever waiting for
        # an EOF that never comes. Started with start_new_session=True,
        # so killing the whole process group takes the real process(es)
        # down too and the pipe actually closes.
        import os
        import signal
        os.killpg(os.getpgid(session["proc"].pid), signal.SIGKILL)
    except ProcessLookupError:
        pass  # already gone
    except Exception as exc:
        return f"Error killing session: {exc}"
    # Exit is settled by _pump_session_output's own (timeout-guarded) wait
    # once stdout hits EOF — don't wait() here too, since calling it from
    # two places at once caused a hang during development.
    for _ in range(20):
        if not session["alive"]:
            break
        await asyncio.sleep(0.25)
    return f"Killed session {session_id}."


def _run_shell_list(conversation_id: str) -> str:
    sessions = [s for s in _shell_sessions.values() if s["conversation_id"] == conversation_id]
    if not sessions:
        return "No shell sessions for this conversation."
    lines = []
    for s in sessions:
        status = "running" if s["alive"] else f"exited (code {s['exit_code']})"
        lines.append(f"{s['id']}: {status} — {s['command']}")
    return "\n".join(lines)


def _run_read_file(args: dict, max_chars: int, workdir: str | None = None) -> str:
    path = args.get("path")
    if not path:
        return "Error: no path given."
    try:
        text = _resolve_path(path, workdir).read_text(errors="ignore")
        return text[:max_chars]
    except Exception as exc:
        return f"Error reading file: {exc}"


def _run_write_file(args: dict, workdir: str | None = None) -> str:
    path = args.get("path")
    content = args.get("content", "")
    mode = args.get("mode", "overwrite")
    if not path:
        return "Error: no path given."
    try:
        p = _resolve_path(path, workdir)
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with open(p, "a") as f:
                f.write(content)
        else:
            p.write_text(content)
        return f"Wrote {len(content)} chars to {path} (mode={mode})."
    except Exception as exc:
        return f"Error writing file: {exc}"


def _run_edit_file(args: dict, workdir: str | None = None) -> str:
    """Find-and-replace on an existing file — same safety contract as
    Claude Code's own Edit tool: old_string must match exactly once, or
    the call fails loudly instead of guessing which occurrence was
    meant (or silently editing the wrong one)."""
    path = args.get("path")
    old_string = args.get("old_string")
    new_string = args.get("new_string", "")
    if not path:
        return "Error: no path given."
    if old_string is None:
        return "Error: old_string is required."
    if old_string == new_string:
        return "Error: old_string and new_string are identical — nothing to change."
    try:
        p = _resolve_path(path, workdir)
        text = p.read_text()
    except Exception as exc:
        return f"Error reading file: {exc}"
    count = text.count(old_string)
    if count == 0:
        return "Error: old_string not found in file — it must match the file's contents exactly, including whitespace."
    if count > 1:
        return f"Error: old_string appears {count} times in the file — include more surrounding context so it matches exactly once."
    try:
        p.write_text(text.replace(old_string, new_string, 1))
        return f"Replaced 1 occurrence in {path}."
    except Exception as exc:
        return f"Error writing file: {exc}"


def _run_list_dir(args: dict, max_chars: int, workdir: str | None = None) -> str:
    path = args.get("path", ".")
    try:
        entries = sorted(_resolve_path(path, workdir).iterdir())
        lines = [f"{'d' if e.is_dir() else 'f'} {e.name}" for e in entries]
        return "\n".join(lines)[:max_chars] or "(empty directory)"
    except Exception as exc:
        return f"Error listing directory: {exc}"


async def _run_web_search(args: dict, max_chars: int) -> str:
    from app.services import web_service
    query = args.get("query", "")
    if not query.strip():
        return "Error: no query given."
    results = await web_service.search(query)
    if not results:
        return "No results found."
    lines = [f"- {r['title']} ({r['url']})\n  {r['snippet']}" for r in results]
    return "\n".join(lines)[:max_chars]


async def _run_fetch_url(args: dict, max_chars: int) -> str:
    from app.services import web_service
    url = args.get("url", "")
    if not url.strip():
        return "Error: no url given."
    page = await web_service.fetch_url(url)
    if not page:
        return f"Could not fetch {url}."
    return f"[{page['title']}]\n{page['text']}"[:max_chars]


async def _run_browser_navigate(args: dict, conversation_id: str, max_chars: int) -> str:
    from app.services import browser_service
    try:
        return await browser_service.navigate(conversation_id, str(args.get("url", "")), max_chars)
    except browser_service.BrowserError as exc:
        return f"Error: {exc}"


async def _run_browser_click(args: dict, conversation_id: str) -> str:
    from app.services import browser_service
    selector = str(args.get("selector", ""))
    if not selector:
        return "Error: no selector given."
    try:
        return await browser_service.click(conversation_id, selector)
    except browser_service.BrowserError as exc:
        return f"Error: {exc}"


async def _run_browser_type(args: dict, conversation_id: str) -> str:
    from app.services import browser_service
    selector = str(args.get("selector", ""))
    if not selector:
        return "Error: no selector given."
    try:
        return await browser_service.type_text(
            conversation_id, selector, str(args.get("text", "")), bool(args.get("submit", False))
        )
    except browser_service.BrowserError as exc:
        return f"Error: {exc}"


async def _run_browser_get_text(args: dict, conversation_id: str, max_chars: int) -> str:
    from app.services import browser_service
    try:
        return await browser_service.get_text(conversation_id, args.get("selector") or None, max_chars)
    except browser_service.BrowserError as exc:
        return f"Error: {exc}"


async def _run_browser_close(conversation_id: str) -> str:
    from app.services import browser_service
    closed = await browser_service.close_session(conversation_id)
    return "Closed the browser session." if closed else "No browser session was open."


async def _execute_tool(
    tool: str, args: dict, timeout: float, max_chars: int, workdir: str | None = None,
    conversation_id: str | None = None,
) -> str:
    if tool == "bash":
        return await _run_bash(args, timeout, max_chars, workdir)
    if tool == "read_file":
        return _run_read_file(args, max_chars, workdir)
    if tool == "write_file":
        return _run_write_file(args, workdir)
    if tool == "edit_file":
        return _run_edit_file(args, workdir)
    if tool == "list_dir":
        return _run_list_dir(args, max_chars, workdir)
    if tool == "web_search":
        return await _run_web_search(args, max_chars)
    if tool == "fetch_url":
        return await _run_fetch_url(args, max_chars)
    if tool == "git":
        return await _run_git(args, timeout, max_chars, workdir)
    if tool == "run_checks":
        return await _run_checks(args, workdir)
    if tool == "shell_start":
        return await _run_shell_start(args, conversation_id, workdir)
    if tool == "shell_output":
        return _run_shell_output(args, conversation_id)
    if tool == "shell_write_stdin":
        return await _run_shell_write_stdin(args, conversation_id)
    if tool == "shell_kill":
        return await _run_shell_kill(args, conversation_id)
    if tool == "shell_list":
        return _run_shell_list(conversation_id)
    if tool == "browser_navigate":
        return await _run_browser_navigate(args, conversation_id, max_chars)
    if tool == "browser_click":
        return await _run_browser_click(args, conversation_id)
    if tool == "browser_type":
        return await _run_browser_type(args, conversation_id)
    if tool == "browser_get_text":
        return await _run_browser_get_text(args, conversation_id, max_chars)
    if tool == "browser_close":
        return await _run_browser_close(conversation_id)
    return f"Error: unknown tool '{tool}'."


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_step(raw: str) -> dict | None:
    m = _JSON_OBJ_RE.search(raw or "")
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


async def _run_subagent(
    task: str, conversation_id: str, workdir: str | None,
    mcp_tools: list[dict], mcp_by_name: dict, model: str,
    max_chars: int, cmd_timeout: float, parent_call_id: str,
) -> AsyncIterator[dict]:
    """A self-contained, unattended sub-loop: same tool set and JSON
    protocol as the main agent loop, but with no approval gates of its
    own — spawning it was already the one approval (or the conversation
    is in semi/full mode), so the user has effectively agreed to let this
    delegated task run without a prompt at every step. Every tool call it
    makes is still logged to the audit trail and streamed to the UI
    (tagged with the parent call's id) — nothing it does is invisible,
    it just doesn't pause. Can't spawn further sub-agents, which bounds
    both the blast radius and the cost of a single delegation."""
    from app.services import mcp_service

    max_iters = int(settings.get("agent_subagent_max_iterations", 8))
    system = _build_system_prompt(mcp_tools) + (
        f"\n\nWorking directory: {workdir}\n"
        "Relative paths resolve against this directory automatically."
        if workdir else ""
    ) + (
        "\n\nYou are a sub-agent delegated a single focused task by another agent. "
        "Work autonomously — there's no user to ask for approval or clarification. "
        "When you're done, respond with a concise {\"final\": \"...\"} summary of what "
        "you did and what you found."
    )
    loop_messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    client = OllamaClient()
    final_text: str | None = None

    for _ in range(max_iters):
        try:
            raw = await client.chat(model, loop_messages)
        except OllamaError as exc:
            final_text = f"Sub-agent error: {exc}"
            break

        step = _parse_step(raw)
        if not step:
            final_text = raw.strip()
            break
        if "final" in step:
            final_text = str(step["final"])
            break

        tool = str(step.get("tool", ""))
        args = step.get("args", {}) if isinstance(step.get("args"), dict) else {}
        if tool == "spawn_subagent":
            loop_messages.append({"role": "assistant", "content": json.dumps(step)})
            loop_messages.append({"role": "user", "content": "Error: sub-agents can't spawn further sub-agents. Do this task directly."})
            continue
        if tool not in TOOLS and tool not in mcp_by_name:
            loop_messages.append({"role": "assistant", "content": json.dumps(step)})
            allowed = ", ".join(n for n in TOOLS if n != "spawn_subagent")
            loop_messages.append({"role": "user", "content": f"Error: unknown tool '{tool}'. Choose one of: {allowed}."})
            continue

        risk = classify_risk(tool, args)
        diff, previous_content, had_previous_file = _preview_diff(tool, args, workdir)
        call_id = _log_call(conversation_id, tool, args, risk, diff, previous_content, had_previous_file)
        yield {"type": "tool_call", "id": call_id, "tool": tool, "args": args, "risk": risk,
               "diff": diff, "subagent_of": parent_call_id}

        if tool in mcp_by_name:
            mcp_tool = mcp_by_name[tool]
            server = mcp_service.get_server(mcp_tool["server_id"])
            result = (
                await mcp_service.call_tool(server, mcp_tool["tool_name"], args, max_chars)
                if server else f"Error: MCP server '{mcp_tool['server_name']}' is no longer configured."
            )
        else:
            result = await _execute_tool(tool, args, cmd_timeout, max_chars, workdir, conversation_id)
        _resolve_call(call_id, "executed", result)
        yield {"type": "tool_result", "id": call_id, "tool": tool, "result": result, "subagent_of": parent_call_id}

        loop_messages.append({"role": "assistant", "content": json.dumps(step)})
        loop_messages.append({"role": "user", "content": f"Tool result for {tool}:\n{result}"})

    if final_text is None:
        final_text = f"Sub-agent hit its step limit ({max_iters}) without finishing — partial progress only."
    yield {"type": "subagent_done", "text": final_text}


async def run_agent_turn(
    conversation_id: str,
    user_text: str,
    attachment_ids: list[str],
    history_last_model: str | None = None,
    model_override: str | None = None,
) -> AsyncIterator[dict]:
    """Async generator of structured events for the SSE layer to wrap:
    route, tool_call, tool_pending, tool_result, tool_denied, token, done,
    error. Mirrors orchestrator.run_turn's shape but drives a multi-step
    loop instead of one retrieve-then-answer turn."""
    from app.db import storage
    from app.services.orchestrator import build_turn_context, _build_system_context

    mode = settings.get("agent_mode", "manual")
    max_iters = int(settings.get("agent_max_iterations", 8))
    cmd_timeout = float(settings.get("agent_command_timeout_seconds", 60))
    max_chars = int(settings.get("agent_output_max_chars", 4000))
    approval_timeout = float(settings.get("agent_approval_timeout_seconds", 600))

    ctx = await build_turn_context(attachment_ids)
    history = storage.get_messages(conversation_id)
    system_text, _sys_citations = await _build_system_context(conversation_id, user_text)
    workdir = storage.get_conversation_workdir(conversation_id)

    from app.services import mcp_service
    mcp_tools = await mcp_service.list_all_tools()
    mcp_by_name = {t["agent_tool_name"]: t for t in mcp_tools}

    router = ModelRouter()
    if model_override:
        decision = RouteDecision(
            model=model_override, role="general", reason="Manually selected for this message.",
            confidence=1.0,
        )
    else:
        decision: RouteDecision = await router.decide(
            text=user_text, has_image=ctx.has_image, has_video=ctx.has_video,
            has_long_document=ctx.has_long_document, history_last_model=history_last_model,
        )
    parent_for_user = storage.get_last_active_message_id(conversation_id)
    user_msg = storage.add_message(
        conversation_id, "user", user_text,
        attachments=ctx.attachment_summaries, parent_id=parent_for_user,
    )
    assistant_parent_id = user_msg["id"]

    yield {"type": "route", "model": decision.model, "role": decision.role,
           "reason": decision.reason, "confidence": decision.confidence}

    system = _build_system_prompt(mcp_tools) + (
        f"\n\nContext about this user:\n{system_text}" if system_text else ""
    ) + (
        f"\n\nWorking directory for this conversation: {workdir}\n"
        "Relative paths (in bash, read_file, write_file, edit_file, list_dir) resolve "
        "against this directory automatically — you don't need to give full paths."
        if workdir else ""
    )
    trimmed_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-int(settings.get("max_context_messages", 24)):]
    ]
    # Resume a checkpointed run: if the previous agent turn on this
    # conversation stopped at the iteration cap without finishing, it stashed
    # its full loop state. Pick up from exactly there (with the new user
    # message appended as a nudge) instead of starting cold, then clear the
    # checkpoint so we don't resume it twice.
    checkpoint = storage.get_agent_checkpoint(conversation_id)
    if checkpoint:
        try:
            loop_messages = json.loads(checkpoint["state"])
            loop_messages.append({"role": "user", "content": user_text})
            storage.clear_agent_checkpoint(conversation_id)
            yield {"type": "resumed", "iterations_used": checkpoint.get("iterations_used", 0)}
        except (json.JSONDecodeError, TypeError):
            storage.clear_agent_checkpoint(conversation_id)
            loop_messages = (
                [{"role": "system", "content": system}] + trimmed_history
                + [{"role": "user", "content": user_text}]
            )
    else:
        loop_messages = (
            [{"role": "system", "content": system}] + trimmed_history
            + [{"role": "user", "content": user_text}]
        )

    client = OllamaClient()
    final_text: str | None = None
    tool_seq: list[str] = []
    had_failure = False
    last_failure: str | None = None

    # Plan-first mode: the model drafts a plan, you approve it once, then it
    # executes the whole thing unattended (no per-tool-call gates). Distinct
    # from "full" in that you see and sign off on the plan before anything
    # runs. Reuses the same approval-future machinery as tool approvals.
    effective_mode = mode
    if mode == "plan":
        plan_prompt = loop_messages + [{
            "role": "user",
            "content": (
                'Before doing anything, outline your plan as a JSON object: '
                '{"plan": ["step 1", "step 2", ...]}. List the concrete steps — '
                "commands you'll run, files you'll change — you intend to take. "
                "Do NOT call any tool yet; return only the plan."
            ),
        }]
        try:
            raw_plan = await client.chat(decision.model, plan_prompt)
        except OllamaError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        parsed_plan = _parse_step(raw_plan)
        if parsed_plan and isinstance(parsed_plan.get("plan"), list):
            steps = [str(s) for s in parsed_plan["plan"]]
            plan_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
        else:
            plan_text = raw_plan.strip()
        plan_id = str(uuid.uuid4())
        yield {"type": "plan_pending", "id": plan_id, "plan": plan_text}
        approved = await _await_approval(plan_id, approval_timeout)
        if not approved:
            yield {"type": "plan_rejected", "id": plan_id}
            final_text = "Plan rejected — I haven't made any changes. Tell me what to adjust and I'll re-plan."
        else:
            yield {"type": "plan_approved", "id": plan_id}
            loop_messages.append({"role": "assistant", "content": f"My plan:\n{plan_text}"})
            loop_messages.append({
                "role": "user",
                "content": "Approved. Execute this plan now, one tool call per step, then give a final summary.",
            })
            effective_mode = "full"  # approved plan runs unattended

    for _ in range(max_iters):
        if final_text is not None:
            break  # plan was rejected before the loop even started
        try:
            raw = await client.chat(decision.model, loop_messages)
        except OllamaError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        step = _parse_step(raw)
        if not step:
            # Model didn't follow the protocol — treat its raw text as the
            # final answer rather than failing the whole turn.
            final_text = raw.strip()
            break

        if "final" in step:
            final_text = str(step["final"])
            break

        tool = str(step.get("tool", ""))
        args = step.get("args", {}) if isinstance(step.get("args"), dict) else {}
        if tool not in TOOLS and tool not in mcp_by_name:
            loop_messages.append({"role": "assistant", "content": json.dumps(step)})
            allowed = ", ".join(list(TOOLS) + list(mcp_by_name))
            loop_messages.append({"role": "user", "content": f"Error: unknown tool '{tool}'. Choose one of: {allowed}."})
            continue

        risk = classify_risk(tool, args)
        diff, previous_content, had_previous_file = _preview_diff(tool, args, workdir)
        call_id = _log_call(conversation_id, tool, args, risk, diff, previous_content, had_previous_file, run_id=assistant_parent_id)
        tool_seq.append(tool)
        yield {"type": "tool_call", "id": call_id, "tool": tool, "args": args, "risk": risk, "diff": diff}

        needs_approval = effective_mode == "manual" or (effective_mode == "semi" and risk == "risky")
        if needs_approval:
            yield {"type": "tool_pending", "id": call_id, "tool": tool, "args": args, "risk": risk, "diff": diff}
            approved = await _await_approval(call_id, approval_timeout)
            if not approved:
                _resolve_call(call_id, "denied")
                yield {"type": "tool_denied", "id": call_id}
                loop_messages.append({"role": "assistant", "content": json.dumps(step)})
                loop_messages.append({"role": "user", "content": "Tool call denied by the user. Try a different approach or give a final answer."})
                continue

        if tool == "spawn_subagent":
            task_desc = str(args.get("task", "")).strip()
            if not task_desc:
                result = "Error: no task given."
            else:
                summary = None
                async for sub_event in _run_subagent(
                    task_desc, conversation_id, workdir, mcp_tools, mcp_by_name,
                    decision.model, max_chars, cmd_timeout, call_id,
                ):
                    if sub_event["type"] == "subagent_done":
                        summary = sub_event["text"]
                    else:
                        yield sub_event
                result = summary or "Sub-agent finished with no summary."
        elif tool in mcp_by_name:
            mcp_tool = mcp_by_name[tool]
            server = mcp_service.get_server(mcp_tool["server_id"])
            result = (
                await mcp_service.call_tool(server, mcp_tool["tool_name"], args, max_chars)
                if server else f"Error: MCP server '{mcp_tool['server_name']}' is no longer configured."
            )
        else:
            result = await _execute_tool(tool, args, cmd_timeout, max_chars, workdir, conversation_id)
        _resolve_call(call_id, "executed", result)
        yield {"type": "tool_result", "id": call_id, "tool": tool, "result": result}
        if isinstance(result, str) and result.startswith("Error:"):
            had_failure = True
            last_failure = f"{tool}: {result[:200]}"

        loop_messages.append({"role": "assistant", "content": json.dumps(step)})
        loop_messages.append({"role": "user", "content": f"Tool result for {tool}:\n{result}"})

        # Auto-check feedback loop: after a file edit, optionally run the
        # configured test/lint command and feed the pass/fail back into the
        # loop as its own audited tool call, so the model reacts to a broken
        # build/test without having to remember to check.
        if (tool in ("edit_file", "write_file")
                and settings.get("agent_auto_check")
                and str(settings.get("agent_check_command", "")).strip()
                and not result.startswith("Error")):
            check_id = _log_call(conversation_id, "run_checks", {}, "safe")
            yield {"type": "tool_call", "id": check_id, "tool": "run_checks", "args": {}, "risk": "safe", "diff": None}
            check_result = await _run_checks({}, workdir)
            _resolve_call(check_id, "executed", check_result)
            yield {"type": "tool_result", "id": check_id, "tool": "run_checks", "result": check_result}
            loop_messages.append({"role": "user", "content": f"(automatic) {check_result}"})

    checkpointed = False
    if final_text is None:
        # Hit the iteration cap without finishing — stash the full loop state
        # so the next message resumes instead of restarting. The system prompt
        # is dropped from the saved state (it's rebuilt fresh on resume) to
        # keep the checkpoint compact.
        try:
            saveable = [m for m in loop_messages if m.get("role") != "system"]
            storage.save_agent_checkpoint(
                conversation_id, json.dumps(saveable), decision.model, max_iters
            )
            checkpointed = True
        except Exception as exc:
            log.warning("agent.checkpoint_save_failed", error=str(exc))
        final_text = (
            "I hit the step limit "
            f"({max_iters} tool calls) before finishing. I've saved my progress — "
            "send another message (e.g. \"continue\") and I'll pick up right where I left off."
        )
    else:
        # Finished normally — make sure no stale checkpoint lingers so a later
        # unrelated turn doesn't accidentally resume this one.
        storage.clear_agent_checkpoint(conversation_id)

    # Pseudo-stream the final answer so the UI keeps its typewriter effect
    # even though the loop itself wasn't token-streamed.
    for chunk in re.findall(r"\S+\s*", final_text):
        yield {"type": "token", "text": chunk}

    new_skill = None
    if tool_seq:
        signature = "|".join(tool_seq)
        try:
            new_skill = storage.record_skill_run(conversation_id, signature, tool_seq, user_text)
        except Exception as exc:
            log.warning("agent.skill_detection_failed", error=str(exc))
        # Error-driven self-scripting: a tool failed mid-turn but the agent
        # still reached a real answer — that recovery path (what it tried
        # instead) is worth remembering so the next attempt at a similar
        # task skips straight to what actually works.
        if had_failure and not checkpointed:
            try:
                correction_id = storage.record_skill_correction(
                    conversation_id, last_failure, tool_seq, user_text
                )
                if correction_id and not new_skill:
                    new_skill = correction_id
            except Exception as exc:
                log.warning("agent.correction_recording_failed", error=str(exc))

    yield {"type": "done", "full_text": final_text, "model": decision.model,
           "role": decision.role, "reason": decision.reason,
           "parent_id": assistant_parent_id, "checkpointed": checkpointed,
           "new_skill": new_skill}
