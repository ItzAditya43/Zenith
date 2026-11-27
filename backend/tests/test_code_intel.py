"""Workspace code intelligence: symbols, definitions, references, checks."""
from __future__ import annotations

import shutil

import pytest


@pytest.fixture
def project(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "store.py").write_text(
        "MAX_ITEMS = 5\n\nclass Store:\n    def get_item(self, key):\n        return key\n\n"
        "def load_store(path: str) -> Store:\n    return Store()\n"
    )
    (tmp_path / "app" / "main.py").write_text("from app.store import load_store\n\ns = load_store('x')\nx: int = 'nope'\n")
    (tmp_path / "web.ts").write_text("export function renderPage(id: string) {\n  return id;\n}\nconst x = renderPage('a');\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.js").write_text("function load_store() {}\n")
    return tmp_path


def test_symbols_definition_references(project):
    from app.services import code_intel as ci

    names = [(s["name"], s["kind"]) for s in ci.symbols(project, "ls")]
    assert ("load_store", "function") in names  # subsequence match
    assert ci.symbols(project, "Store")[0] == {"name": "Store", "kind": "class", "path": "app/store.py", "line": 3}
    assert [(d["path"], d["line"]) for d in ci.definitions(project, "get_item")] == [("app/store.py", 4)]
    assert ci.definitions(project, "renderPage")[0]["path"] == "web.ts"
    refs = ci.references(project, "load_store")["results"]
    assert {(r["path"], r["line"]) for r in refs} == {("app/store.py", 7), ("app/main.py", 1), ("app/main.py", 3)}
    assert [r["definition"] for r in refs if r["path"] == "app/store.py"] == [True]
    assert ci.references(project, "bad name!")["results"] == []


def test_parse_checker_output(project):
    from app.services.code_intel import _parse

    out = (f"app/main.py:4:10: error: Incompatible types in assignment  [assignment]\n"
           f"web.ts(4,7): error TS2322: Type 'string' is not assignable to type 'number'.\n"
           f"  {project}/app/store.py:5:16 - warning: Unused expression\n"
           f"Found 1 error in 1 file\nsomething unrelated\n")
    ps = _parse(out, project, "x")
    assert [(p["path"], p["line"], p["severity"]) for p in ps] == [
        ("app/main.py", 4, "error"), ("web.ts", 4, "error"), ("app/store.py", 5, "warning")]
    assert ps[1]["message"].startswith("TS2322")


@pytest.mark.skipif(not shutil.which("mypy"), reason="mypy not installed")
async def test_project_check_runs_mypy(project):
    from app.services import code_intel as ci

    (project / "pyproject.toml").write_text("[project]\nname='p'\n")
    res = await ci.project_check(project)
    assert any(r["tool"] in ("mypy", "pyright") for r in res["ran"])
    assert any(p["path"] == "app/main.py" and p["line"] == 4 for p in res["problems"])


def test_api(client, project):
    from app.db import storage

    c = storage.create_conversation("code")
    storage.set_conversation_workdir(c["id"], str(project))
    base = f"/api/conversations/{c['id']}/code"
    assert client.get(f"{base}/symbols?q=Store").json()[0]["name"] == "Store"
    assert client.get(f"{base}/definition?name=load_store").json()[0]["line"] == 7
    assert len(client.get(f"{base}/references?name=load_store").json()["results"]) == 3


@pytest.mark.skipif(not shutil.which("mypy"), reason="mypy not installed")
async def test_agent_type_check_loop_feeds_errors_back(fake_ollama, tmp_path):
    from app.core.config import settings
    from app.db import storage
    from app.services import agent_service
    from tests.conftest import collect

    (tmp_path / "pyproject.toml").write_text("[project]\nname='p'\n")
    (tmp_path / "calc.py").write_text("def double(n: int) -> int:\n    return n * 2\n")
    conv = storage.create_conversation("tc")
    storage.set_conversation_workdir(conv["id"], str(tmp_path))
    settings.update({"agent_enabled": True, "agent_mode": "full", "agent_type_check": True, "agent_type_check_rounds": 2,
                     "agent_auto_check": False, "memory_enabled": False, "recall_enabled": False,
                     "folder_recall_enabled": False, "notes_todos_context_enabled": False, "agent_sandbox": "off"})
    try:
        fake_ollama.tool("write_file", path="use.py", content="from calc import double\n\nx: str = double(2)\n")
        fake_ollama.tool("write_file", path="use.py", content="from calc import double\n\nx: int = double(2)\n")
        fake_ollama.final("fixed")
        events = await collect(agent_service.run_agent_turn(conv["id"], "use double", [], model_override="llama3.2:3b"))
        checks = [e["result"] for e in events if e.get("type") == "tool_result" and e.get("tool") == "type_check"]
        assert len(checks) == 2
        assert "error" in checks[0] and "use.py:3" in checks[0]
        assert checks[1].startswith("Type check passed")
        assert "Type check found" in fake_ollama.prompts()[1]
    finally:
        settings.update({"agent_type_check": False})
