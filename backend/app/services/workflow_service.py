"""Visual workflows: a graph of nodes the user wires together on a canvas,
run for real against their own models.

Node types
  input    the text the run starts with
  agent    a model with its own instructions; sees what flows into it
  memory   recalls what Zenith remembers about the input (no model call)
  web      searches the web for the input (a clearly marked outbound call)
  review   pauses the run until the user approves or rejects
  output   the final result

A node runs once every node feeding it has finished; independent branches
run at the same time. Each step is reported as an event (the same events
the UI draws as a live trace). Cycles are rejected before anything runs.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator

from app.core.logging import get_logger
from app.db.storage import _conn
from app.services.ollama_client import OllamaClient

log = get_logger(__name__)

NODE_TYPES = {"input", "agent", "memory", "web", "review", "output"}
MAX_NODES = 40
REVIEW_TIMEOUT_S = 15 * 60
CONTEXT_CHARS = 6000

# run_id -> {node_id: Future[bool]} for review nodes waiting on the user.
_pending: dict[str, dict[str, asyncio.Future]] = {}


# ---- storage ---------------------------------------------------------------

def _row(r) -> dict:
    d = dict(r)
    d["graph"] = json.loads(d["graph"])
    return d


def list_workflows() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        return [_row(r) for r in rows]


def get_workflow(wid: str) -> dict | None:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM workflows WHERE id = ?", (wid,)).fetchone()
        return _row(r) if r else None


def save_workflow(name: str, graph: dict, wid: str | None = None) -> dict:
    validate_graph(graph, structural_only=True)
    now = time.time()
    with _conn() as conn:
        if wid and conn.execute("SELECT 1 FROM workflows WHERE id = ?", (wid,)).fetchone():
            conn.execute(
                "UPDATE workflows SET name = ?, graph = ?, updated_at = ? WHERE id = ?",
                (name, json.dumps(graph), now, wid),
            )
        else:
            wid = uuid.uuid4().hex[:12]
            conn.execute(
                "INSERT INTO workflows (id, name, graph, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (wid, name, json.dumps(graph), now, now),
            )
    return get_workflow(wid)  # type: ignore[return-value]


def delete_workflow(wid: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM workflow_runs WHERE workflow_id = ?", (wid,))
        conn.execute("DELETE FROM workflows WHERE id = ?", (wid,))


def list_runs(wid: str, limit: int = 20) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM workflow_runs WHERE workflow_id = ? ORDER BY started_at DESC LIMIT ?", (wid, limit)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["trace"] = json.loads(d["trace"]) if d.get("trace") else []
        out.append(d)
    return out


# ---- graph checks ------------------------------------------------------------

def validate_graph(graph: dict, structural_only: bool = False) -> dict[str, list[str]]:
    """Returns {node_id: [upstream ids]}; raises ValueError for anything that
    can't run (unknown type, bad edge, cycle, no input/output)."""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if len(nodes) > MAX_NODES:
        raise ValueError(f"Too many nodes (limit {MAX_NODES}).")
    ids = set()
    for n in nodes:
        if n.get("type") not in NODE_TYPES:
            raise ValueError(f"Unknown node type: {n.get('type')!r}")
        if n["id"] in ids:
            raise ValueError("Duplicate node id.")
        ids.add(n["id"])
    ups: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        if e.get("source") not in ids or e.get("target") not in ids:
            raise ValueError("An edge points at a node that doesn't exist.")
        if e["source"] == e["target"]:
            raise ValueError("A node can't connect to itself.")
        if e["source"] not in ups[e["target"]]:
            ups[e["target"]].append(e["source"])
    # Kahn's algorithm: anything left over is in a cycle.
    indeg = {i: len(u) for i, u in ups.items()}
    queue = [i for i, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        cur = queue.pop()
        seen += 1
        for t, u in ups.items():
            if cur in u:
                indeg[t] -= 1
                if indeg[t] == 0:
                    queue.append(t)
    if seen != len(ids):
        raise ValueError("The workflow loops back on itself. Remove the cycle to run it.")
    if not structural_only:
        types = [n["type"] for n in nodes]
        if "input" not in types:
            raise ValueError("Add an Input node to start the workflow.")
        if "output" not in types:
            raise ValueError("Add an Output node to finish the workflow.")
    return ups


# ---- running ---------------------------------------------------------------------

def resolve_review(run_id: str, node_id: str, approve: bool) -> bool:
    fut = _pending.get(run_id, {}).get(node_id)
    if not fut or fut.done():
        return False
    fut.set_result(approve)
    return True


async def _default_model() -> str | None:
    from app.services.router import ModelRegistry, ModelRouter

    registry = ModelRegistry()
    installed = await registry.models()
    router = ModelRouter(registry=registry)
    for role in ("general", "small_fast"):
        model = router._match_capability(role, installed)  # noqa: SLF001
        if model:
            return model
    return installed[0] if installed else None


def _context(parts: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"[{label}]\n{text[:CONTEXT_CHARS]}" for label, text in parts if text)


async def _run_node(node: dict, inputs: list[tuple[str, str]], run_input: str, run_id: str,
                    emit) -> str:
    kind = node["type"]
    data = node.get("data") or {}
    upstream = _context(inputs)
    if kind == "input":
        return run_input
    if kind == "output":
        return "\n\n".join(t for _, t in inputs) or run_input
    if kind == "memory":
        from app.services import memory_service

        block = memory_service.memory_block(query=run_input)
        return block.strip() or "(nothing relevant in memory)"
    if kind == "web":
        from app.services import web_service

        query = (data.get("query") or "").strip() or run_input
        try:
            results = await asyncio.wait_for(web_service.search(query, max_results=5), 25)
        except Exception as exc:  # noqa: BLE001 — offline or blocked: carry on without it
            return f"(web search unavailable: {exc.__class__.__name__})"
        if not results:
            return "(no web results)"
        return "\n".join(f"- {r.get('title','')}: {r.get('snippet','') or r.get('body','')} ({r.get('url','')})" for r in results)
    if kind == "review":
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        _pending.setdefault(run_id, {})[node["id"]] = fut
        await emit({"type": "review_request", "node": node["id"], "preview": upstream[:1500]})
        try:
            approved = await asyncio.wait_for(fut, REVIEW_TIMEOUT_S)
        except TimeoutError:
            raise RuntimeError("Review timed out with no answer.") from None
        finally:
            _pending.get(run_id, {}).pop(node["id"], None)
        if not approved:
            raise RuntimeError("Rejected at review.")
        return "\n\n".join(t for _, t in inputs)
    # agent
    model = (data.get("model") or "").strip() or await _default_model()
    if not model:
        raise RuntimeError("No model available. Install or add a model first.")
    system = (data.get("prompt") or "").strip() or "You are a careful assistant. Do the task you are given."
    user = run_input if not upstream else f"Task: {run_input}\n\nWhat the earlier steps produced:\n{upstream}"
    out: list[str] = []
    async for piece in OllamaClient().chat_stream(
        model, [{"role": "system", "content": system}, {"role": "user", "content": user}]
    ):
        text = str(piece)
        if type(piece).__name__ == "ThinkingDelta":
            continue
        out.append(text)
        await emit({"type": "token", "node": node["id"], "text": text})
    return "".join(out).strip()


async def run_workflow(graph: dict, run_input: str, workflow_id: str | None = None) -> AsyncIterator[dict]:
    """Yields events: run_start, node_start, token, review_request, node_done,
    node_error, node_skipped, run_done."""
    run_id = uuid.uuid4().hex[:12]
    try:
        ups = validate_graph(graph)
    except ValueError as exc:
        yield {"type": "run_error", "error": str(exc)}
        return
    nodes = {n["id"]: n for n in graph["nodes"]}
    queue: asyncio.Queue = asyncio.Queue()
    trace: list[dict] = []
    started = time.time()

    async def emit(ev: dict) -> None:
        await queue.put(ev)

    results: dict[str, str] = {}
    failed: set[str] = set()
    done_events = {i: asyncio.Event() for i in nodes}

    async def worker(nid: str) -> None:
        node = nodes[nid]
        for u in ups[nid]:
            await done_events[u].wait()
        t0 = time.time()
        if any(u in failed for u in ups[nid]):
            failed.add(nid)
            await emit({"type": "node_skipped", "node": nid, "reason": "An earlier step didn't finish."})
            done_events[nid].set()
            return
        await emit({"type": "node_start", "node": nid})
        try:
            inputs = [((nodes[u].get("data") or {}).get("label") or nodes[u]["type"], results[u]) for u in ups[nid]]
            results[nid] = await _run_node(node, inputs, run_input, run_id, emit)
            await emit({"type": "node_done", "node": nid, "output": results[nid], "ms": int((time.time() - t0) * 1000)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a node failing must not crash the run
            failed.add(nid)
            log.warning("workflow.node_failed", node=nid, error=str(exc))
            await emit({"type": "node_error", "node": nid, "error": str(exc) or exc.__class__.__name__})
        finally:
            done_events[nid].set()

    yield {"type": "run_start", "run_id": run_id, "nodes": len(nodes)}
    tasks = [asyncio.create_task(worker(n)) for n in nodes]

    async def finisher() -> None:
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.put(None)

    fin = asyncio.create_task(finisher())
    try:
        while True:
            ev = await queue.get()
            if ev is None:
                break
            if ev["type"] != "token":
                trace.append({**ev, "t": round(time.time() - started, 2)})
            yield ev
    finally:
        for t in tasks:
            t.cancel()
        fin.cancel()
        _pending.pop(run_id, None)
        out_nodes = [i for i, n in nodes.items() if n["type"] == "output"]
        final = "\n\n".join(results[i] for i in out_nodes if i in results)
        status = "done" if final and not failed else ("failed" if failed else "stopped")
        _save_run(run_id, workflow_id, started, status, run_input, final, trace)
    yield {"type": "run_done", "run_id": run_id, "status": status, "output": final}


def _save_run(run_id, workflow_id, started, status, run_input, final, trace) -> None:
    if not workflow_id:
        return
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO workflow_runs (id, workflow_id, started_at, finished_at, status, input, output, trace)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, workflow_id, started, time.time(), status, run_input, final, json.dumps(trace)),
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("workflow.save_run_failed", error=str(exc))
