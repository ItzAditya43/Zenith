"""Agent-mode note_*/todo_* tools, and the automatic notes/to-dos context
injection every chat turn gets (not just agent mode) — see
orchestrator.py::_build_system_context and agent_service.py's
note_add/note_update/note_delete/todo_add/todo_update/todo_delete."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def temp_data_dir(monkeypatch):
    import tempfile

    d = tempfile.mkdtemp(prefix="cortex-test-")
    monkeypatch.setenv("CORTEX_DATA_DIR", d)
    from app.core import config as cfg

    cfg.refresh_paths()
    cfg.settings.reload()
    from app.db import storage
    storage.init_db()
    yield Path(d)
    cfg.refresh_paths()
    cfg.settings.reload()


def test_note_add_update_delete_via_agent_tools(temp_data_dir):
    from app.db import storage
    from app.services import agent_service

    out = agent_service._run_note_add({"content": "buy milk"})
    assert "Saved note" in out
    note_id = out.split()[-1].rstrip(".")
    assert any(n["content"] == "buy milk" for n in storage.list_notes())

    out = agent_service._run_note_update({"note_id": note_id, "content": "buy oat milk"})
    assert "Updated note" in out
    assert any(n["content"] == "buy oat milk" for n in storage.list_notes())

    out = agent_service._run_note_delete({"note_id": note_id})
    assert "Deleted note" in out
    assert not any(n["id"] == note_id for n in storage.list_notes())


def test_note_add_requires_content(temp_data_dir):
    from app.services import agent_service

    out = agent_service._run_note_add({})
    assert out.startswith("Error")


def test_todo_add_update_delete_via_agent_tools(temp_data_dir):
    from app.db import storage
    from app.services import agent_service

    out = agent_service._run_todo_add({"text": "email the landlord"})
    assert "Added to-do" in out
    todo_id = out.split()[-1].rstrip(":").split(":")[0] if ":" in out else out.split()[-1]
    todo_id = [t["id"] for t in storage.list_todos() if t["text"] == "email the landlord"][0]

    out = agent_service._run_todo_update({"todo_id": todo_id, "status": "in_progress"})
    assert "Updated to-do" in out
    match = next(t for t in storage.list_todos() if t["id"] == todo_id)
    assert match["status"] == "in_progress"

    out = agent_service._run_todo_delete({"todo_id": todo_id})
    assert "Deleted to-do" in out
    assert not any(t["id"] == todo_id for t in storage.list_todos())


def test_todo_update_rejects_bad_status(temp_data_dir):
    from app.db import storage
    from app.services import agent_service

    todo = storage.create_todo("test")
    out = agent_service._run_todo_update({"todo_id": todo["id"], "status": "bogus"})
    assert out.startswith("Error")


def test_note_and_todo_tools_classified_safe_except_delete():
    from app.services import agent_service

    assert agent_service.classify_risk("note_add", {}) == "safe"
    assert agent_service.classify_risk("note_update", {}) == "safe"
    assert agent_service.classify_risk("note_delete", {}) == "risky"
    assert agent_service.classify_risk("todo_add", {}) == "safe"
    assert agent_service.classify_risk("todo_update", {}) == "safe"
    assert agent_service.classify_risk("todo_delete", {}) == "risky"


def test_system_context_includes_notes_and_open_todos(temp_data_dir):
    from app.db import storage
    from app.services.orchestrator import _build_system_context

    storage.create_conversation("t")
    conv = storage.create_conversation("t2")
    storage.create_note("remember to water the plants")
    storage.create_todo("finish the report")
    done_todo = storage.create_todo("already done")
    storage.update_todo(done_todo["id"], status="done")

    text, _citations = asyncio.run(_build_system_context(conv["id"], "hello"))
    assert "water the plants" in text
    assert "finish the report" in text
    assert "already done" not in text  # done todos excluded from the "open" list


def test_system_context_notes_todos_can_be_disabled(temp_data_dir):
    from app.core import config as cfg
    from app.db import storage
    from app.services.orchestrator import _build_system_context

    conv = storage.create_conversation("t")
    storage.create_note("secret note")
    cfg.settings.set("notes_todos_context_enabled", False)

    text, _citations = asyncio.run(_build_system_context(conv["id"], "hello"))
    assert "secret note" not in text
