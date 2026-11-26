"""Background agent runs (queue, run without a client, approvals, cancel,
restart recovery) and the run review that lists what a run changed."""
from __future__ import annotations

import asyncio

import pytest

from tests.test_agent_loop import agent  # noqa: F401 — shared fixture


async def _wait(bid, statuses, timeout=10.0):
    from app.services import background_runs as br

    for _ in range(int(timeout / 0.02)):
        run = br.get_run(bid)
        if run["status"] in statuses:
            return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"stuck in {br.get_run(bid)['status']}")


async def test_queued_run_finishes_and_is_reviewable(agent):  # noqa: F811
    from app.db import storage
    from app.services import background_runs as br

    agent["fake"].tool("edit_file", path="hello.py", old_string="hello", new_string="goodbye").final("Changed the greeting.")
    run = br.enqueue(agent["conv"], "change the greeting", model="llama3.2:3b")
    assert run["status"] == "queued"
    done = await _wait(run["id"], ("done", "failed"))
    assert done["status"] == "done", done.get("error")
    assert done["summary"] == "Changed the greeting." and done["run_id"]
    assert any(e["type"] == "tool_result" for e in done["log"])
    assert (agent["work"] / "hello.py").read_text() == "print('goodbye')\n"
    msgs = storage.get_messages(agent["conv"])
    assert msgs[-1]["role"] == "assistant" and msgs[-1]["content"] == "Changed the greeting."

    rev = br.review(done["run_id"])
    assert rev["prompt"] == "change the greeting" and rev["reply"] == "Changed the greeting."
    assert rev["files"][0]["path"] == "hello.py" and rev["files"][0]["applied"]
    assert "goodbye" in rev["files"][0]["diffs"][0]
    assert rev["counts"]["edits_applied"] == 1 and rev["background"]["id"] == run["id"]


async def test_waiting_for_approval_then_cancel(agent):  # noqa: F811
    from app.core.config import settings
    from app.services import background_runs as br

    settings.update({"agent_mode": "manual"})
    agent["fake"].tool("bash", command="echo hi").final("ok")
    run = br.enqueue(agent["conv"], "run a command", model="llama3.2:3b")
    waiting = await _wait(run["id"], ("waiting",))
    assert any(e["type"] == "tool_pending" for e in waiting["log"])
    assert br.cancel(run["id"]) is True
    final = await _wait(run["id"], ("cancelled",))
    assert final["finished_at"]
    assert br.cancel(run["id"]) is False


async def test_runs_in_one_chat_go_one_at_a_time(agent):  # noqa: F811
    from app.services import background_runs as br

    agent["fake"].final("first").final("second")
    a = br.enqueue(agent["conv"], "one", model="llama3.2:3b")
    b = br.enqueue(agent["conv"], "two", model="llama3.2:3b")
    ra = await _wait(a["id"], ("done",))
    rb = await _wait(b["id"], ("done",))
    assert ra["finished_at"] <= rb["started_at"]
    assert (ra["summary"], rb["summary"]) == ("first", "second")


def test_restart_marks_cut_off_runs_interrupted(fake_ollama):
    from app.db import storage
    from app.services import background_runs as br

    c = storage.create_conversation("x")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(br, "_kick", lambda: None)
        run = br.enqueue(c["id"], "task")
    br._update(run["id"], status="running")
    assert br.recover_interrupted() == 1
    assert br.get_run(run["id"])["status"] == "interrupted"


def test_api_requires_agent_tools(client):
    from app.core.config import settings
    from app.db import storage

    c = storage.create_conversation("x")
    settings.update({"agent_enabled": False})
    r = client.post("/api/agent/background", json={"conversation_id": c["id"], "prompt": "hi"})
    assert r.status_code == 400 and "agent tools" in r.json()["detail"]
    assert client.get("/api/agent/background").json() == []
