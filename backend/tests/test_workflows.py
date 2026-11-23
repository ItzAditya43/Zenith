"""Visual workflows: graph validation, ordered/parallel execution against a
scripted model, failure isolation, review gating, and the saved-run trace."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeOllama


@pytest.fixture
def client(temp_data_dir):
    from app.main import app

    with TestClient(app) as c:
        yield c


def N(i, t, **data):
    return {"id": i, "type": t, "position": {"x": 0, "y": 0}, "data": data}


def E(a, b):
    return {"id": f"{a}-{b}", "source": a, "target": b}


def collect(client, graph, text="hello", workflow_id=None):
    events = []
    with client.stream("POST", "/api/workflows/run", json={"graph": graph, "input": text, "workflow_id": workflow_id}) as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:]))
    return events


def test_rejects_cycles_and_missing_ends(client):
    cyc = {"nodes": [N("a", "agent"), N("b", "agent")], "edges": [E("a", "b"), E("b", "a")]}
    assert client.post("/api/workflows", json={"name": "x", "graph": cyc}).status_code == 400
    ev = collect(client, {"nodes": [N("a", "agent")], "edges": []})
    assert ev[0]["type"] == "run_error" and "Input" in ev[0]["error"]


def test_runs_a_chain_in_order(client, monkeypatch):
    fake = FakeOllama().install(monkeypatch)
    fake.queue("draft one", "polished two")
    g = {
        "nodes": [N("i", "input"), N("a", "agent", prompt="draft", model="llama3.2:3b"),
                  N("b", "agent", prompt="polish", model="llama3.2:3b"), N("o", "output")],
        "edges": [E("i", "a"), E("a", "b"), E("b", "o")],
    }
    ev = collect(client, g, "write a haiku")
    done = [e for e in ev if e["type"] == "node_done"]
    assert [e["node"] for e in done] == ["i", "a", "b", "o"]
    assert ev[-1]["type"] == "run_done" and ev[-1]["status"] == "done"
    assert "polished two" in ev[-1]["output"]
    assert "draft one" in fake.calls[1]["messages"][1]["content"]  # b saw a's output


def test_a_failed_node_skips_what_depends_on_it(client, monkeypatch):
    fake = FakeOllama().install(monkeypatch)
    fake.queue(RuntimeError("model fell over"))
    g = {"nodes": [N("i", "input"), N("a", "agent", model="llama3.2:3b"), N("o", "output")],
         "edges": [E("i", "a"), E("a", "o")]}
    ev = collect(client, g)
    kinds = {(e["type"], e.get("node")) for e in ev}
    assert ("node_error", "a") in kinds and ("node_skipped", "o") in kinds
    assert ev[-1]["status"] == "failed"


def test_review_node_waits_for_approval(client, monkeypatch):
    FakeOllama().install(monkeypatch).queue("the plan")
    g = {"nodes": [N("i", "input"), N("a", "agent", model="llama3.2:3b"), N("r", "review"), N("o", "output")],
         "edges": [E("i", "a"), E("a", "r"), E("r", "o")]}
    from app.services import workflow_service as wf

    async def go(approve):
        got = []
        gen = wf.run_workflow(g, "x")
        async for ev in gen:
            got.append(ev)
            if ev["type"] == "review_request":
                assert wf.resolve_review(got[0]["run_id"], "r", approve)
        return got

    ok = asyncio.run(go(True))
    assert ok[-1]["status"] == "done"
    FakeOllama().install(monkeypatch).queue("the plan")
    no = asyncio.run(go(False))
    assert no[-1]["status"] == "failed" and any(e["type"] == "node_error" and "Rejected" in e["error"] for e in no)


def test_save_list_runs_and_delete(client, monkeypatch):
    FakeOllama().install(monkeypatch).queue("hi there")
    g = {"nodes": [N("i", "input"), N("a", "agent", model="llama3.2:3b"), N("o", "output")],
         "edges": [E("i", "a"), E("a", "o")]}
    wfd = client.post("/api/workflows", json={"name": "demo", "graph": g}).json()
    assert client.get("/api/workflows").json()[0]["name"] == "demo"
    collect(client, g, "yo", workflow_id=wfd["id"])
    runs = client.get(f"/api/workflows/{wfd['id']}/runs").json()
    assert runs[0]["status"] == "done" and runs[0]["trace"]
    client.delete(f"/api/workflows/{wfd['id']}")
    assert client.get("/api/workflows").json() == []


def test_web_node_failure_does_not_stop_the_run(client, monkeypatch):
    from app.services import web_service

    async def boom(*_a, **_k):
        raise RuntimeError("offline")

    monkeypatch.setattr(web_service, "search", boom)
    g = {"nodes": [N("i", "input"), N("w", "web"), N("o", "output")], "edges": [E("i", "w"), E("w", "o")]}
    ev = collect(client, g)
    assert ev[-1]["status"] == "done" and "unavailable" in ev[-1]["output"]
