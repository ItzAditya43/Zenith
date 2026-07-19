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
        "description": "Write or append text to a file, creating parent dirs as needed. "
                        "Args: path (string), content (string), mode ('overwrite'|'append', default 'overwrite')."
    },
    "list_dir": {"description": "List a directory's contents. Args: path (string)."},
    "web_search": {"description": "Search the web. Args: query (string)."},
    "fetch_url": {"description": "Fetch and extract the readable text of a URL. Args: url (string)."},
}

_SYSTEM_PROMPT = """You are Cortex operating in agent mode: you can use tools across multiple
steps to satisfy the user's request, instead of answering from memory alone.

Available tools:
""" + "\n".join(f"- {name}: {spec['description']}" for name, spec in TOOLS.items()) + """

Respond with EXACTLY ONE JSON object and nothing else — no prose, no markdown fence:
  To call a tool:      {"tool": "<name>", "args": {...}}
  To give a final answer: {"final": "<answer text, written for the user>"}

Rules:
- One tool call per turn. You will see its result before deciding the next step.
- Only use a tool when it actually helps; otherwise answer directly with {"final": ...}.
- Never invent a tool result — wait for the real one.
- Once you have enough information, stop and return {"final": ...}. Don't over-explore.
"""

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


def classify_risk(tool: str, args: dict[str, Any]) -> str:
    """Returns "safe" or "risky". Safe calls auto-run in "semi" mode;
    risky calls always pause for approval outside "full" mode."""
    if tool in ("read_file", "list_dir", "web_search", "fetch_url"):
        return "safe"
    if tool == "write_file":
        return "risky"
    if tool == "bash":
        cmd = str(args.get("command", "")).strip()
        first = cmd.split(" ", 1)[0] if cmd else ""
        if first in _SAFE_BASH_CMDS and not any(tok in cmd for tok in _UNSAFE_BASH_TOKENS):
            return "safe"
        return "risky"
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

def _log_call(conversation_id: str, tool: str, args: dict, risk: str) -> str:
    call_id = str(uuid.uuid4())
    with _conn() as conn:
        conn.execute(
            """INSERT INTO tool_calls (id, conversation_id, tool, args, risk, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (call_id, conversation_id, tool, json.dumps(args)[:MAX_ARG_LOG_CHARS], risk, time.time()),
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


# --- Tool execution ---------------------------------------------------------

async def _run_bash(args: dict, timeout: float, max_chars: int) -> str:
    command = str(args.get("command", "")).strip()
    cwd = args.get("cwd") or None
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


def _run_read_file(args: dict, max_chars: int) -> str:
    from pathlib import Path
    path = args.get("path")
    if not path:
        return "Error: no path given."
    try:
        text = Path(path).read_text(errors="ignore")
        return text[:max_chars]
    except Exception as exc:
        return f"Error reading file: {exc}"


def _run_write_file(args: dict) -> str:
    from pathlib import Path
    path = args.get("path")
    content = args.get("content", "")
    mode = args.get("mode", "overwrite")
    if not path:
        return "Error: no path given."
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with open(p, "a") as f:
                f.write(content)
        else:
            p.write_text(content)
        return f"Wrote {len(content)} chars to {path} (mode={mode})."
    except Exception as exc:
        return f"Error writing file: {exc}"


def _run_list_dir(args: dict, max_chars: int) -> str:
    from pathlib import Path
    path = args.get("path", ".")
    try:
        entries = sorted(Path(path).iterdir())
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


async def _execute_tool(tool: str, args: dict, timeout: float, max_chars: int) -> str:
    if tool == "bash":
        return await _run_bash(args, timeout, max_chars)
    if tool == "read_file":
        return _run_read_file(args, max_chars)
    if tool == "write_file":
        return _run_write_file(args)
    if tool == "list_dir":
        return _run_list_dir(args, max_chars)
    if tool == "web_search":
        return await _run_web_search(args, max_chars)
    if tool == "fetch_url":
        return await _run_fetch_url(args, max_chars)
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


async def run_agent_turn(
    conversation_id: str,
    user_text: str,
    attachment_ids: list[str],
    history_last_model: str | None = None,
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
    system_text = await _build_system_context(conversation_id, user_text)

    router = ModelRouter()
    decision: RouteDecision = await router.decide(
        text=user_text, has_image=ctx.has_image, has_video=ctx.has_video,
        has_long_document=ctx.has_long_document, history_last_model=history_last_model,
    )
    storage.add_message(conversation_id, "user", user_text, attachments=ctx.attachment_summaries)

    yield {"type": "route", "model": decision.model, "role": decision.role,
           "reason": decision.reason, "confidence": decision.confidence}

    system = _SYSTEM_PROMPT + (f"\n\nContext about this user:\n{system_text}" if system_text else "")
    trimmed_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-int(settings.get("max_context_messages", 24)):]
    ]
    loop_messages: list[dict] = (
        [{"role": "system", "content": system}] + trimmed_history
        + [{"role": "user", "content": user_text}]
    )

    client = OllamaClient()
    final_text: str | None = None

    for _ in range(max_iters):
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
        if tool not in TOOLS:
            loop_messages.append({"role": "assistant", "content": json.dumps(step)})
            loop_messages.append({"role": "user", "content": f"Error: unknown tool '{tool}'. Choose one of: {', '.join(TOOLS)}."})
            continue

        risk = classify_risk(tool, args)
        call_id = _log_call(conversation_id, tool, args, risk)
        yield {"type": "tool_call", "id": call_id, "tool": tool, "args": args, "risk": risk}

        needs_approval = mode == "manual" or (mode == "semi" and risk == "risky")
        if needs_approval:
            yield {"type": "tool_pending", "id": call_id, "tool": tool, "args": args, "risk": risk}
            approved = await _await_approval(call_id, approval_timeout)
            if not approved:
                _resolve_call(call_id, "denied")
                yield {"type": "tool_denied", "id": call_id}
                loop_messages.append({"role": "assistant", "content": json.dumps(step)})
                loop_messages.append({"role": "user", "content": "Tool call denied by the user. Try a different approach or give a final answer."})
                continue

        result = await _execute_tool(tool, args, cmd_timeout, max_chars)
        _resolve_call(call_id, "executed", result)
        yield {"type": "tool_result", "id": call_id, "tool": tool, "result": result}

        loop_messages.append({"role": "assistant", "content": json.dumps(step)})
        loop_messages.append({"role": "user", "content": f"Tool result for {tool}:\n{result}"})

    if final_text is None:
        final_text = (
            "I wasn't able to finish this within the step limit "
            f"({max_iters} tool calls). Here's what I found so far — "
            "you can ask me to continue."
        )

    # Pseudo-stream the final answer so the UI keeps its typewriter effect
    # even though the loop itself wasn't token-streamed.
    for chunk in re.findall(r"\S+\s*", final_text):
        yield {"type": "token", "text": chunk}

    yield {"type": "done", "full_text": final_text, "model": decision.model,
           "role": decision.role, "reason": decision.reason}
