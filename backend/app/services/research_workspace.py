"""Research workspaces built on saved Deep Research reports.

- Notes: your own notes kept with the report.
- Claims: the report's key claims, each tied to the numbered sources that
  support it (or marked as unsupported, i.e. the model's own inference),
  extracted once and cached.
- Updates: re-run the same research later; the result is saved as a newer
  version of the report, with which sources are new and which dropped out.
"""
from __future__ import annotations

import asyncio
import json
import re

from app.core.logging import get_logger
from app.db import storage

log = get_logger(__name__)

_reruns: dict[str, dict] = {}  # report id -> {"status", "new_id", "error"}

_CLAIMS_PROMPT = """Below is a research report and its numbered sources. List the report's key claims (3–8).
For each, give the numbers of the sources that directly support it. If no listed source supports it, give [] — that marks it as the writer's own inference.

Return ONLY JSON: [{{"claim": "<one sentence>", "sources": [1, 3]}}]

Report:
{answer}

Sources:
{sources}"""


async def _model() -> str | None:
    from app.services.router import ModelRegistry, ModelRouter

    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    return router._match_capability("general", installed) or router._match_capability("small_fast", installed) or (installed[0] if installed else None)  # noqa: SLF001


def _parse_claims(raw: str, n_sources: int) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not str(item.get("claim") or "").strip():
            continue
        refs = sorted({int(x) for x in item.get("sources") or [] if str(x).isdigit() and 1 <= int(x) <= n_sources})
        out.append({"claim": str(item["claim"]).strip()[:400], "sources": refs, "supported": bool(refs)})
    return out[:8]


async def extract_claims(report_id: str, force: bool = False) -> list[dict]:
    from app.services.ollama_client import OllamaClient

    report = storage.get_research_report(report_id)
    if not report:
        raise LookupError("No such report.")
    if report.get("claims") is not None and not force:
        return report["claims"]
    model = await _model()
    if not model:
        raise RuntimeError("No local model available.")
    sources = report["sources"]
    listing = "\n".join(f"[{i}] {s.get('title') or s.get('url')} — {s.get('url', '')}" for i, s in enumerate(sources, 1)) or "(none)"
    raw = await OllamaClient().chat(model, [{"role": "user", "content": _CLAIMS_PROMPT.format(answer=report["answer"][:8000], sources=listing)}])
    claims = _parse_claims(raw, len(sources))
    storage.update_research_report(report_id, claims=claims)
    return claims


def versions(report_id: str) -> list[dict]:
    """Every version of this research, oldest first."""
    all_reports = {r["id"]: r for r in storage.list_research_reports()}
    root = all_reports.get(report_id)
    while root and root.get("parent_id") in all_reports:
        root = all_reports[root["parent_id"]]
    if not root:
        return []
    chain, frontier = [root], [root["id"]]
    while frontier:
        nxt = [r for r in all_reports.values() if r.get("parent_id") in frontier]
        chain += nxt
        frontier = [r["id"] for r in nxt]
    return [{"id": r["id"], "created_at": r["created_at"], "sources": len(r["sources"])} for r in sorted(chain, key=lambda r: r["created_at"])]


def diff_sources(old: dict, new: dict) -> dict:
    a = {s.get("url") for s in old["sources"] if s.get("url")}
    b = {s.get("url") for s in new["sources"] if s.get("url")}
    return {"added": [s for s in new["sources"] if s.get("url") in b - a],
            "dropped": [s for s in old["sources"] if s.get("url") in a - b]}


async def _rerun(report_id: str) -> None:
    from app.core.rate_limit import conversation_lock
    from app.services import research_service

    report = storage.get_research_report(report_id)
    state = _reruns[report_id]
    if report is None:
        state.update(status="failed", error="The report was deleted.")
        return
    try:
        cid = report.get("conversation_id")
        if not cid or not storage.get_conversation(cid):
            cid = storage.create_conversation(f"Research: {report['query'][:60]}")["id"]
        collected: list[dict] = []
        full = ""
        async with conversation_lock(cid):
            async for ev in research_service.run_deep_research(cid, report["query"], []):
                if ev.get("type") == "sources":
                    collected = ev.get("sources", [])
                elif ev.get("type") == "done":
                    full = (ev.get("full_text") or "").strip()
                    if full:
                        storage.add_message(cid, "assistant", full, model=ev.get("model"), route_role=ev.get("role"),
                                            route_reason=ev.get("reason"), parent_id=ev.get("parent_id"))
                elif ev.get("type") == "error":
                    raise RuntimeError(ev.get("message") or "Research failed.")
        if not full:
            raise RuntimeError("The research came back empty.")
        new = storage.create_research_report(cid, report["query"], full, collected, parent_id=report_id)
        if report.get("notes"):
            storage.update_research_report(new["id"], notes=report["notes"])
        state.update(status="done", new_id=new["id"], diff=diff_sources(report, new))
    except Exception as exc:  # noqa: BLE001
        log.warning("research.rerun_failed", report_id=report_id, error=str(exc))
        state.update(status="failed", error=str(exc))


def start_rerun(report_id: str) -> dict:
    if not storage.get_research_report(report_id):
        raise LookupError("No such report.")
    cur = _reruns.get(report_id)
    if cur and cur["status"] == "running":
        return cur
    _reruns[report_id] = {"status": "running", "new_id": None, "error": None, "diff": None}
    asyncio.get_running_loop().create_task(_rerun(report_id))
    return _reruns[report_id]


def rerun_status(report_id: str) -> dict:
    return _reruns.get(report_id) or {"status": "idle"}
