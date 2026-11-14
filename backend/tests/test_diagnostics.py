"""Quick per-file checks after agent edits."""
from __future__ import annotations

import shutil

import pytest

from app.services import diagnostics


async def test_python_syntax_error_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: None)  # force the compile-check path
    f = tmp_path / "bad.py"
    f.write_text("def f(:\n    pass\n")
    problems = await diagnostics.check_file(f, "bad.py")
    assert len(problems) == 1 and problems[0].startswith("bad.py:1:")
    f.write_text("def f():\n    pass\n")
    assert await diagnostics.check_file(f, "bad.py") == []


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
async def test_python_undefined_name_via_ruff(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def total(items):\n    return sum(itms)\n")
    problems = await diagnostics.check_file(f, "m.py")
    assert any("m.py:2:" in p and "F821" in p for p in problems)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
async def test_javascript_syntax_error(tmp_path):
    f = tmp_path / "a.js"
    f.write_text("function f( {\n}\n")
    problems = await diagnostics.check_file(f, "a.js")
    assert problems and problems[0].startswith("a.js:")


async def test_json_and_unknown_types(tmp_path):
    j = tmp_path / "p.json"
    j.write_text('{"a": 1,}')
    assert (await diagnostics.check_file(j, "p.json"))[0].startswith("p.json:1: invalid JSON")
    t = tmp_path / "notes.txt"
    t.write_text("anything")
    assert await diagnostics.check_file(t, "notes.txt") == []


def test_format_for_model():
    assert diagnostics.format_for_model([]) == ""
    assert "- a.py:1: oops" in diagnostics.format_for_model(["a.py:1: oops"])
