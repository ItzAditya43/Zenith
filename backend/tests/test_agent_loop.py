"""The agent tool-use loop (agent_service.run_agent_turn) driven end to end
by a scripted model: approvals, denials, timeouts, protocol slips, the
iteration cap + checkpoint/resume, plan-first mode, sub-agents, file
edits with diff/undo, auto-checks, MCP tools and skill recording."""
from __future__ import annotations

import asyncio
import subprocess

import pytest

from tests.conftest import collect


@pytest.fixture
def agent(fake_ollama, tmp_path):
    from app.core.config import settings
    from app.db import storage

    settings.update({
        "agent_enabled": True, "agent_mode": "full", "agent_max_iterations": 6,
        "agent_approval_timeout_seconds": 30, "memory_enabled": False,
        "recall_enabled": False, "folder_recall_enabled": False,
        "notes_todos_context_enabled": False, "agent_auto_check": False,
        "agent_check_command": "", "agent_sandbox": "off",
    })
    work = tmp_path / "proj"
    work.mkdir()
    (work / "hello.py").write_text("print('hello')\n")
    conv = storage.create_conversation("agent test")
    storage.set_conversation_workdir(conv["id"], str(work))
    return {"conv": conv["id"], "work": work, "fake": fake_ollama}


async def _run(conv, text="do the thing", **kw):
    from app.services import agent_service

    return await collect(agent_service.run_agent_turn(conv, text, [], model_override="llama3.2:3b", **kw))


def _types(events):
    return [e["type"] for e in events]


def _approve_next(approve: bool = True):
    """Background task: approve/deny the first pending call that appears."""
    from app.services import agent_service

    async def _go():
        for _ in range(400):
            if agent_service._pending:
                call_id = next(iter(agent_service._pending))
                agent_service.approve_tool_call(call_id, approve)
                return call_id
            await asyncio.sleep(0.01)
        raise AssertionError("no approval was requested")

    return asyncio.create_task(_go())


# --- basic protocol ----------------------------------------------------------


async def test_tool_then_final_answer(agent):
    agent["fake"].tool("read_file", path="hello.py").final("It prints hello.")
    events = await _run(agent["conv"])
    assert _types(events)[0] == "route"
    result = next(e for e in events if e["type"] == "tool_result")
    assert "print('hello')" in result["result"]
    done = events[-1]
    assert done["type"] == "done" and done["full_text"] == "It prints hello."
    assert "".join(e["text"] for e in events if e["type"] == "token") == "It prints hello."
    # the tool result was fed back to the model on the next step
    assert "Tool result for read_file" in agent["fake"].prompts()[1]


async def test_every_call_is_audited(agent):
    from app.services import agent_service

    agent["fake"].tool("list_dir", path=".").final("done")
    await _run(agent["conv"])
    calls = agent_service.list_tool_calls(agent["conv"])
    assert [c["tool"] for c in calls] == ["list_dir"]
    assert calls[0]["status"] == "executed" and "hello.py" in calls[0]["result"]


async def test_structured_output_schema_is_sent(agent):
    agent["fake"].final("hi")
    await _run(agent["conv"])
    fmt = agent["fake"].calls[0]["format"]
    assert isinstance(fmt, dict) and fmt.get("type") == "object"


async def test_non_json_reply_becomes_the_answer(agent):
    agent["fake"].queue("I would read the file, but here is my answer anyway.")
    events = await _run(agent["conv"])
    assert events[-1]["full_text"].startswith("I would read the file")


async def test_unknown_tool_is_reported_back_to_the_model(agent):
    agent["fake"].tool("teleport", to="mars").final("ok, no teleporting")
    events = await _run(agent["conv"])
    assert "Error: unknown tool 'teleport'" in agent["fake"].prompts()[1]
    assert events[-1]["full_text"] == "ok, no teleporting"


async def test_ollama_error_surfaces_as_error_event(agent):
    from app.services.ollama_client import OllamaError

    agent["fake"].queue(OllamaError("model crashed"))
    events = await _run(agent["conv"])
    assert events[-1] == {"type": "error", "message": "model crashed"}


# --- approvals ----------------------------------------------------------------


async def test_manual_mode_waits_for_approval(agent):
    from app.core.config import settings

    settings.update({"agent_mode": "manual"})
    agent["fake"].tool("read_file", path="hello.py").final("read it")
    task = _approve_next(True)
    events = await _run(agent["conv"])
    await task
    assert _types(events)[1:4] == ["tool_call", "tool_pending", "tool_result"]


async def test_denied_call_is_not_executed(agent):
    from app.core.config import settings
    from app.services import agent_service

    settings.update({"agent_mode": "manual"})
    agent["fake"].tool("write_file", path="evil.txt", content="x").final("fine, I won't")
    task = _approve_next(False)
    events = await _run(agent["conv"])
    await task
    assert "tool_denied" in _types(events)
    assert not (agent["work"] / "evil.txt").exists()
    assert "denied by the user" in agent["fake"].prompts()[1]
    assert agent_service.list_tool_calls(agent["conv"])[0]["status"] == "denied"


async def test_approval_timeout_counts_as_denial(agent):
    from app.core.config import settings

    settings.update({"agent_mode": "manual", "agent_approval_timeout_seconds": 0.05})
    agent["fake"].tool("write_file", path="late.txt", content="x").final("timed out")
    events = await _run(agent["conv"])
    assert "tool_denied" in _types(events)
    assert not (agent["work"] / "late.txt").exists()


async def test_semi_mode_auto_runs_safe_but_gates_risky(agent):
    from app.core.config import settings

    settings.update({"agent_mode": "semi"})
    agent["fake"].tool("read_file", path="hello.py").tool("bash", command="rm hello.py").final("stopped")
    task = _approve_next(False)
    events = await _run(agent["conv"])
    await task
    pending = [e for e in events if e["type"] == "tool_pending"]
    assert [p["tool"] for p in pending] == ["bash"]  # the safe read never paused
    assert (agent["work"] / "hello.py").exists()


async def test_semi_mode_gates_reads_outside_workdir(agent):
    from app.core.config import settings

    settings.update({"agent_mode": "semi"})
    agent["fake"].tool("read_file", path="/etc/hostname").final("ok")
    task = _approve_next(False)
    events = await _run(agent["conv"])
    await task
    assert [e["tool"] for e in events if e["type"] == "tool_pending"] == ["read_file"]


async def test_project_mode_overrides_global_mode(agent):
    from app.core.config import settings
    from app.db import storage

    settings.update({"agent_mode": "full"})
    project = storage.create_project("p")
    storage.set_conversation_project(agent["conv"], project["id"])
    storage.set_project_agent_mode(project["id"], "manual")
    agent["fake"].tool("read_file", path="hello.py").final("ok")
    task = _approve_next(True)
    events = await _run(agent["conv"])
    await task
    assert "tool_pending" in _types(events)


# --- iteration cap + resume -----------------------------------------------------


async def test_iteration_cap_checkpoints_and_next_turn_resumes(agent):
    from app.core.config import settings
    from app.db import storage

    settings.update({"agent_max_iterations": 2})
    agent["fake"].tool("list_dir", path=".").tool("list_dir", path=".")
    events = await _run(agent["conv"])
    done = events[-1]
    assert done["checkpointed"] is True and "step limit" in done["full_text"]
    assert storage.get_agent_checkpoint(agent["conv"]) is not None

    agent["fake"].final("finished after resuming")
    events = await _run(agent["conv"], "continue")
    assert events[0]["type"] == "resumed" or "resumed" in _types(events)
    assert events[-1]["full_text"] == "finished after resuming"
    assert storage.get_agent_checkpoint(agent["conv"]) is None
    # the resumed loop carried the earlier tool results forward
    resumed_messages = agent["fake"].calls[-1]["messages"]
    assert any("Tool result for list_dir" in m["content"] for m in resumed_messages)


# --- plan-first mode ----------------------------------------------------------------


async def test_plan_mode_runs_unattended_after_approval(agent):
    from app.core.config import settings

    settings.update({"agent_mode": "plan"})
    agent["fake"].queue({"plan": ["read hello.py", "summarise"]})
    agent["fake"].tool("write_file", path="out.txt", content="planned").final("done per plan")
    task = _approve_next(True)
    events = await _run(agent["conv"])
    await task
    types = _types(events)
    assert types.index("plan_pending") < types.index("plan_approved") < types.index("tool_result")
    assert "tool_pending" not in types  # approved plan runs without per-step gates
    assert (agent["work"] / "out.txt").read_text() == "planned"
    plan_event = next(e for e in events if e["type"] == "plan_pending")
    assert plan_event["plan"] == "1. read hello.py\n2. summarise"


async def test_plan_rejection_changes_nothing(agent):
    from app.core.config import settings

    settings.update({"agent_mode": "plan"})
    agent["fake"].queue({"plan": ["delete everything"]})
    task = _approve_next(False)
    events = await _run(agent["conv"])
    await task
    assert "plan_rejected" in _types(events)
    assert "tool_call" not in _types(events)
    assert "haven't made any changes" in events[-1]["full_text"]


# --- files: diff preview + undo --------------------------------------------------------


async def test_edit_file_previews_diff_and_can_be_reverted(agent):
    from app.services import agent_service

    agent["fake"].tool("edit_file", path="hello.py", old_string="hello", new_string="bye").final("edited")
    events = await _run(agent["conv"])
    call = next(e for e in events if e["type"] == "tool_call")
    assert "-print('hello')" in call["diff"] and "+print('bye')" in call["diff"]
    assert (agent["work"] / "hello.py").read_text() == "print('bye')\n"

    agent_service.revert_tool_call(call["id"])
    assert (agent["work"] / "hello.py").read_text() == "print('hello')\n"
    with pytest.raises(agent_service.AgentError):
        agent_service.revert_tool_call(call["id"])  # already reverted


async def test_reverting_a_created_file_deletes_it(agent):
    from app.services import agent_service

    agent["fake"].tool("write_file", path="new.txt", content="fresh").final("made")
    events = await _run(agent["conv"])
    call = next(e for e in events if e["type"] == "tool_call")
    assert (agent["work"] / "new.txt").exists()
    agent_service.revert_tool_call(call["id"])
    assert not (agent["work"] / "new.txt").exists()


async def test_ambiguous_edit_is_refused(agent):
    (agent["work"] / "dup.txt").write_text("x\nx\n")
    agent["fake"].tool("edit_file", path="dup.txt", old_string="x", new_string="y").final("ok")
    events = await _run(agent["conv"])
    result = next(e for e in events if e["type"] == "tool_result")["result"]
    assert "appears 2 times" in result
    assert (agent["work"] / "dup.txt").read_text() == "x\nx\n"


# --- checks + skills ----------------------------------------------------------------------


async def test_auto_check_runs_after_successful_edit(agent):
    from app.core.config import settings

    settings.update({"agent_auto_check": True, "agent_check_command": "python3 hello.py"})
    agent["fake"].tool("write_file", path="hello.py", content="print('checked')\n").final("ok")
    events = await _run(agent["conv"])
    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["tool"] for r in results] == ["write_file", "run_checks"]
    assert "Checks PASSED" in results[1]["result"] and "checked" in results[1]["result"]
    assert "(automatic) Checks PASSED" in agent["fake"].calls[1]["messages"][-1]["content"]


async def test_run_checks_reports_failure(agent):
    from app.services import agent_service

    out = await agent_service._run_checks({"command": "python3 -c 'import sys; sys.exit(3)'"}, str(agent["work"]))
    assert out.startswith("Checks FAILED (exit 3")


async def test_tool_failure_then_recovery_is_recorded(agent):
    from app.db import storage

    agent["fake"].tool("read_file", path="missing.py").tool("read_file", path="hello.py").final("recovered")
    done = (await _run(agent["conv"]))[-1]
    skills = storage.list_skills()
    assert [s["name"] for s in skills] == ["Recovery: read_file failed → read_file → read_file"]
    assert done["new_skill"]["id"] == skills[0]["id"]


async def test_repeated_tool_sequence_is_promoted_to_a_skill(agent):
    from app.db import storage

    for _ in range(2):
        agent["fake"].tool("list_dir", path=".").tool("read_file", path="hello.py").final("ok")
        done = (await _run(agent["conv"]))[-1]
    assert done["new_skill"]["name"] == "list_dir → read_file"
    assert [s["name"] for s in storage.list_skills()] == ["list_dir → read_file"]


# --- sub-agents -----------------------------------------------------------------------------


async def test_subagent_runs_its_own_loop_and_reports_back(agent):
    agent["fake"].tool("spawn_subagent", task="list the files")
    agent["fake"].tool("list_dir", path=".")          # sub-agent's step
    agent["fake"].final("found hello.py")              # sub-agent's summary
    agent["fake"].final("the sub-agent found hello.py")  # parent's answer
    events = await _run(agent["conv"])
    sub = [e for e in events if e.get("subagent_of")]
    assert [e["type"] for e in sub] == ["tool_call", "tool_result"]
    parent_result = [e for e in events if e["type"] == "tool_result" and not e.get("subagent_of")][0]
    assert parent_result["result"] == "found hello.py"
    assert events[-1]["full_text"] == "the sub-agent found hello.py"


async def test_subagent_cannot_spawn_another(agent):
    agent["fake"].tool("spawn_subagent", task="recurse")
    agent["fake"].tool("spawn_subagent", task="deeper")
    agent["fake"].final("stopped recursing")
    agent["fake"].final("done")
    await _run(agent["conv"])
    assert any("can't spawn further sub-agents" in p for p in agent["fake"].prompts())


# --- MCP tools --------------------------------------------------------------------------------


async def test_mcp_tool_calls_route_to_the_server(agent, monkeypatch):
    from app.services import mcp_service

    tools = [{"agent_tool_name": "mcp__cal__today", "server_id": "s1", "server_name": "cal",
              "tool_name": "today", "description": "today's events", "input_schema": {}}]
    seen = {}

    async def fake_list_all():
        return tools

    async def fake_call(server, tool_name, args, max_chars=4000):
        seen.update(server=server, tool=tool_name, args=args)
        return "Standup at 10:00"

    monkeypatch.setattr(mcp_service, "list_all_tools", fake_list_all)
    monkeypatch.setattr(mcp_service, "get_server", lambda sid: {"id": sid, "name": "cal"})
    monkeypatch.setattr(mcp_service, "call_tool", fake_call)

    agent["fake"].tool("mcp__cal__today", day="mon").final("You have standup.")
    events = await _run(agent["conv"])
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["risk"] == "risky"  # external tools are never auto-trusted
    assert seen == {"server": {"id": "s1", "name": "cal"}, "tool": "today", "args": {"day": "mon"}}
    assert "mcp__cal__today: today's events" in agent["fake"].calls[0]["messages"][0]["content"]


# --- shell sessions + git ----------------------------------------------------------------------


async def test_shell_session_lifecycle(agent):
    from app.services import agent_service

    conv, work = agent["conv"], str(agent["work"])
    started = await agent_service._run_shell_start({"command": "echo ready; sleep 30"}, conv, work)
    assert "ready" in started
    session_id = started.split()[2]
    assert "running" in agent_service._run_shell_list(conv)
    assert "Killed" in await agent_service._run_shell_kill({"session_id": session_id}, conv)
    assert agent_service._get_session(session_id, "other-conversation") is None


async def test_git_tool_strips_coauthor_trailers(agent):
    from app.services import agent_service

    work = str(agent["work"])
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=work, check=True)
    out = await agent_service._run_git(
        {"op": "commit", "message": "add hello\n\nCo-Authored-By: Some Bot <bot@example.com>"}, 10, 4000, work
    )
    assert "add hello" in out
    body = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=work, capture_output=True, text=True).stdout
    assert "Co-Authored-By" not in body
    assert "hello.py" in subprocess.run(["git", "show", "--stat", "HEAD"], cwd=work, capture_output=True, text=True).stdout
    status = await agent_service._run_git({"op": "status"}, 10, 4000, work)
    assert status.startswith("## ") and "hello.py" not in status  # committed, nothing pending


# --- tool dispatch: notes, to-dos, shell I/O, browser errors -------------------------------


async def test_note_and_todo_tools_round_trip(agent):
    from app.db import storage
    from app.services import agent_service

    run = agent_service._execute_tool
    out = await run("note_add", {"content": "call the plumber"}, 5, 1000, None, agent["conv"])
    note_id = out.split()[-1].rstrip(".")
    await run("note_update", {"note_id": note_id, "content": "call the plumber at 9"}, 5, 1000, None, agent["conv"])
    assert storage.list_notes()[0]["content"] == "call the plumber at 9"
    assert "Deleted" in await run("note_delete", {"note_id": note_id}, 5, 1000, None, agent["conv"])
    assert storage.list_notes() == []

    out = await run("todo_add", {"text": "file taxes"}, 5, 1000, None, agent["conv"])
    todo_id = out.split()[2].rstrip(":")
    assert "must be one of" in await run("todo_update", {"todo_id": todo_id, "status": "bogus"}, 5, 1000, None, agent["conv"])
    await run("todo_update", {"todo_id": todo_id, "status": "done"}, 5, 1000, None, agent["conv"])
    assert storage.list_todos()[0]["status"] == "done"
    assert "Deleted" in await run("todo_delete", {"todo_id": todo_id}, 5, 1000, None, agent["conv"])

    for tool in ("note_add", "note_update", "note_delete", "todo_add", "todo_update", "todo_delete"):
        assert (await run(tool, {}, 5, 1000, None, agent["conv"])).startswith("Error")
    assert "unknown tool" in await run("nope", {}, 5, 1000, None, agent["conv"])


async def test_shell_session_stdin_and_incremental_output(agent):
    from app.services import agent_service

    conv, work = agent["conv"], str(agent["work"])
    started = await agent_service._run_shell_start({"command": "cat"}, conv, work)
    sid = started.split()[2]
    assert "Sent" in await agent_service._run_shell_write_stdin({"session_id": sid, "text": "ping-123"}, conv)
    for _ in range(40):
        out = agent_service._run_shell_output({"session_id": sid}, conv)
        if "ping-123" in out:
            break
        await asyncio.sleep(0.05)
    assert "ping-123" in out
    assert "no new output" in agent_service._run_shell_output({"session_id": sid}, conv)
    await agent_service._run_shell_kill({"session_id": sid}, conv)
    assert "already exited" in await agent_service._run_shell_write_stdin({"session_id": sid, "text": "x"}, conv)
    assert "no session" in agent_service._run_shell_output({"session_id": "missing"}, conv)
    assert (await agent_service._run_shell_start({"command": ""}, conv, work)).startswith("Error")


async def test_bash_tool_reports_exit_code_stderr_and_timeout(agent):
    from app.services import agent_service

    work = str(agent["work"])
    out = await agent_service._run_bash({"command": "echo out; echo err >&2; exit 4"}, 10, 1000, work)
    assert "exit_code: 4" in out and "stdout:\nout" in out and "stderr:\nerr" in out
    assert "timed out" in await agent_service._run_bash({"command": "sleep 5"}, 0.2, 1000, work)
    assert (await agent_service._run_bash({"command": ""}, 1, 1000, work)).startswith("Error")


async def test_browser_tools_report_errors_instead_of_raising(agent, monkeypatch):
    from app.services import agent_service, browser_service

    async def boom(*args, **kwargs):
        raise browser_service.BrowserError("no chromium here")

    for name in ("navigate", "click", "type_text", "get_text"):
        monkeypatch.setattr(browser_service, name, boom)

    async def closed(conv):
        return False

    monkeypatch.setattr(browser_service, "close_session", closed)
    run = agent_service._execute_tool
    conv = agent["conv"]
    assert "no chromium" in await run("browser_navigate", {"url": "https://x.test"}, 5, 1000, None, conv)
    assert "no chromium" in await run("browser_click", {"selector": "#a"}, 5, 1000, None, conv)
    assert "no chromium" in await run("browser_type", {"selector": "#a", "text": "hi"}, 5, 1000, None, conv)
    assert "no chromium" in await run("browser_get_text", {}, 5, 1000, None, conv)
    assert (await run("browser_click", {}, 5, 1000, None, conv)).startswith("Error")
    assert "No browser session" in await run("browser_close", {}, 5, 1000, None, conv)


async def test_git_tool_ops_and_guards(agent):
    from app.services import agent_service

    work = str(agent["work"])
    assert "working directory" in await agent_service._run_git({"op": "status"}, 10, 4000, None)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    assert "unknown git op" in await agent_service._run_git({"op": "push"}, 10, 4000, work)
    assert "needs a message" in await agent_service._run_git({"op": "commit", "message": " "}, 10, 4000, work)
    out = await agent_service._run_git({"op": "branch", "name": "feature-x"}, 10, 4000, work)
    assert "feature-x" in out
    log = await agent_service._run_git({"op": "log", "count": "bad"}, 10, 4000, work)
    assert isinstance(log, str)  # bad count falls back to the default instead of raising
