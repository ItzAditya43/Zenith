"""Deep Research: multi-step search -> read -> synthesize -> report,
instead of the one-shot "search 5 pages, answer" that the composer's
plain 🔍 toggle does.

Reuses agent_service's JSON-in-text tool-call loop and audit logging,
but deliberately restricted to two tools: web_search and fetch_url. This
is the key safety property — Deep Research never touches bash or the
filesystem, even if the model hallucinates such a call, regardless of
whether agent mode is enabled at all. Because both tools are read-only
against the open web (the same ones the plain search toggle already
uses without confirmation), no approval gate is needed here; it runs
end to end on its own.
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

from app.core.config import settings
from app.core.logging import get_logger
from app.services.agent_service import (
    _log_call,  # noqa: SLF001 — shared audit-log helper, same protocol as agent_service
    _parse_step,  # noqa: SLF001
    _resolve_call,  # noqa: SLF001
    _run_fetch_url,  # noqa: SLF001
    _run_web_search,  # noqa: SLF001
)
from app.services.ollama_client import OllamaClient, OllamaError
from app.services.router import ModelRouter, RouteDecision

log = get_logger(__name__)

_RESEARCH_TOOLS = {
    "web_search": "Search the web. Args: query (string).",
    "fetch_url": "Fetch and read a URL's content. Args: url (string).",
}

_SYSTEM_PROMPT = """You are Cortex in Deep Research mode: instead of answering from a single
search, you investigate a topic across multiple steps and write a structured report.

Available tools:
- web_search: Search the web. Args: query (string).
- fetch_url: Fetch and read a URL's content. Args: url (string).

Respond with EXACTLY ONE JSON object and nothing else — no prose, no markdown fence:
  To call a tool:         {"tool": "<name>", "args": {...}}
  To give the final report: {"final": "<markdown report>"}

Method:
1. Break the topic into 2-4 sub-questions worth investigating separately.
2. web_search each sub-question; fetch_url the 1-3 most promising results per sub-question
   rather than trusting search snippets alone.
3. Once you have enough grounded material, stop searching and write the final report.

Report requirements:
- Markdown with ## section headings, one per sub-question or theme.
- Cite sources inline as [Title](url) using the real titles/urls you fetched.
- State plainly if sources disagree or coverage was thin — don't paper over gaps.
- Don't pad length for its own sake; a well-sourced short report beats a padded long one.
"""


_LEAKED_FINAL_PREFIX_RE = re.compile(r'^\s*\{\s*"final"\s*:\s*"?', re.IGNORECASE)


def _clean_malformed_final(raw: str) -> str:
    """Some models emit `{"final": <content>` and then break strict JSON
    partway through (unescaped quotes/newlines in a long report). Rather
    than leak that wrapper to the user, strip it and any trailing stray
    `"}` off a best-effort raw fallback."""
    text = raw.strip()
    text = _LEAKED_FINAL_PREFIX_RE.sub("", text)
    text = re.sub(r'"?\s*\}\s*$', "", text)
    return text.strip() or raw.strip()


async def run_deep_research(
    conversation_id: str,
    user_text: str,
    attachment_ids: list[str],
    history_last_model: str | None = None,
) -> AsyncIterator[dict]:
    """Same event shape as agent_service.run_agent_turn (route, tool_call,
    tool_result, token, done, error) but with tool_pending/tool_denied
    never emitted — nothing here needs your approval."""
    from app.db import storage
    from app.services.orchestrator import build_turn_context, _build_system_context

    max_iters = int(settings.get("research_max_iterations", 10))
    max_chars = int(settings.get("web_fetch_max_chars", 4000))

    ctx = await build_turn_context(attachment_ids)
    history = storage.get_messages(conversation_id)
    system_text = await _build_system_context(conversation_id, user_text)

    router = ModelRouter()
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

    system = _SYSTEM_PROMPT + (f"\n\nContext about this user:\n{system_text}" if system_text else "")
    trimmed_history = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-int(settings.get("max_context_messages", 24)):]
    ]
    loop_messages: list[dict] = (
        [{"role": "system", "content": system}] + trimmed_history
        + [{"role": "user", "content": f"Research topic: {user_text}"}]
    )

    client = OllamaClient()
    final_text: str | None = None
    sources: list[dict] = []
    used_tool = False

    for i in range(max_iters):
        try:
            raw = await client.chat(decision.model, loop_messages)
        except OllamaError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        step = _parse_step(raw)
        if not step:
            # Malformed JSON. If a tool has already run, take the raw text
            # as a best-effort final answer (better than losing the turn).
            # If nothing has been searched yet, this is a model that's
            # skipping the protocol entirely — force it to try again
            # rather than accepting an ungrounded answer, up to the
            # iteration cap.
            if used_tool or i == max_iters - 1:
                final_text = _clean_malformed_final(raw)
                break
            loop_messages.append({"role": "assistant", "content": raw[:500]})
            loop_messages.append({
                "role": "user",
                "content": "That wasn't valid JSON, and you haven't used a tool yet. "
                            'Respond with ONLY {"tool": "web_search", "args": {"query": "..."}} to start researching.',
            })
            continue

        if "final" in step:
            if not used_tool:
                # Refuse an ungrounded report — this is the exact failure
                # mode where a model fabricates citations instead of
                # admitting it hasn't looked anything up.
                loop_messages.append({"role": "assistant", "content": json.dumps(step)})
                loop_messages.append({
                    "role": "user",
                    "content": "You haven't used web_search or fetch_url yet — Deep Research "
                                "requires actually looking things up before reporting. Never cite "
                                "a source you haven't fetched. Call web_search now.",
                })
                continue
            final_text = str(step["final"])
            break

        tool = str(step.get("tool", ""))
        args = step.get("args", {}) if isinstance(step.get("args"), dict) else {}
        if tool not in _RESEARCH_TOOLS:
            loop_messages.append({"role": "assistant", "content": json.dumps(step)})
            loop_messages.append({
                "role": "user",
                "content": f"Error: unknown or disallowed tool '{tool}'. "
                            f"Deep Research can only use: {', '.join(_RESEARCH_TOOLS)}.",
            })
            continue

        call_id = _log_call(conversation_id, tool, args, "safe")
        yield {"type": "tool_call", "id": call_id, "tool": tool, "args": args, "risk": "safe"}

        if tool == "web_search":
            result = await _run_web_search(args, max_chars)
        else:
            result = await _run_fetch_url(args, max_chars)
            url = args.get("url", "")
            if url and "Could not fetch" not in result:
                title_line = result.split("\n", 1)[0]
                title = title_line.strip("[]") if title_line.startswith("[") else url
                sources.append({"url": url, "title": title})

        used_tool = True
        _resolve_call(call_id, "executed", result)
        yield {"type": "tool_result", "id": call_id, "tool": tool, "result": result}

        loop_messages.append({"role": "assistant", "content": json.dumps(step)})
        loop_messages.append({"role": "user", "content": f"Tool result for {tool}:\n{result}"})

    if final_text is None:
        if used_tool:
            final_text = (
                f"I wasn't able to finish this research within the step limit ({max_iters} "
                "tool calls). Here's what I found so far — ask me to continue if you'd like more."
            )
        else:
            final_text = (
                "I wasn't able to get this model to actually search before answering — "
                "it kept trying to respond from guesswork instead of using web_search. "
                "This works more reliably with a larger/more capable model pinned to the "
                "\"general\" role in Settings -> Model routing."
            )

    if sources:
        yield {"type": "sources", "sources": sources}

    for chunk in re.findall(r"\S+\s*", final_text):
        yield {"type": "token", "text": chunk}

    yield {"type": "done", "full_text": final_text, "model": decision.model,
           "role": decision.role, "reason": decision.reason, "parent_id": assistant_parent_id}
