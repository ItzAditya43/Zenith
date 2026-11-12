"""The agent's grep/glob tools (code_search + their wiring in agent_service)."""
from __future__ import annotations

import os

import pytest

from app.services import code_search


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "app.py").write_text("import os\n\ndef load_config(path):\n    return path\n")
    (tmp_path / "src" / "pkg" / "util.py").write_text("def helper():\n    return load_config('x')\n")
    (tmp_path / "src" / "view.tsx").write_text("export const View = () => null;\n")
    (tmp_path / "README.md").write_text("Call LOAD_CONFIG first.\n")
    (tmp_path / "node_modules" / "dep").mkdir(parents=True)
    (tmp_path / "node_modules" / "dep" / "index.py").write_text("def load_config(): pass\n")
    (tmp_path / "blob.bin").write_bytes(b"\0\1load_config\0")
    return tmp_path


def test_grep_reports_path_line_and_text(repo):
    out = code_search.grep_files(repo, r"def load_config", base=repo)
    assert out == "src/app.py:3: def load_config(path):"


def test_grep_skips_noise_dirs_and_binaries(repo):
    out = code_search.grep_files(repo, "load_config", base=repo)
    assert "node_modules" not in out and "blob.bin" not in out
    assert "src/pkg/util.py:2:" in out


def test_grep_glob_filter_and_ignore_case(repo):
    assert "README.md" not in code_search.grep_files(repo, "load_config", ignore_case=True, glob="*.py", base=repo)
    assert "README.md:1:" in code_search.grep_files(repo, "load_config", ignore_case=True, base=repo)
    assert code_search.grep_files(repo, "load_config", glob="*.md", base=repo).startswith("No matches")


def test_grep_invalid_regex_falls_back_to_literal(repo):
    out = code_search.grep_files(repo, "load_config(", base=repo)
    assert "literal text" in out and "src/app.py:3:" in out


def test_grep_single_file_and_missing_path(repo):
    assert code_search.grep_files(repo / "src" / "app.py", "import", base=repo) == "src/app.py:1: import os"
    assert code_search.grep_files(repo / "nope", "x").startswith("Error")


def test_grep_caps_matches(repo, monkeypatch):
    monkeypatch.setattr(code_search, "MAX_GREP_MATCHES", 2)
    (repo / "many.txt").write_text("hit\n" * 5)
    out = code_search.grep_files(repo, "hit", base=repo).splitlines()
    assert len(out) == 3 and out[-1].startswith("... 3 more matches")


def test_glob_name_pattern_matches_at_any_depth(repo):
    assert code_search.glob_files(repo, "*.py", base=repo).splitlines() == ["src/app.py", "src/pkg/util.py"]


def test_glob_path_pattern(repo):
    assert code_search.glob_files(repo, "src/*.py", base=repo) == "src/app.py"
    assert code_search.glob_files(repo, "src/**/*.py", base=repo).splitlines() == ["src/app.py", "src/pkg/util.py"]
    assert code_search.glob_files(repo, "**/*.tsx", base=repo) == "src/view.tsx"
    assert code_search.glob_files(repo, "*.go", base=repo).startswith("No files match")


def test_symlink_out_of_tree_is_not_searched(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.py").write_text("token = 'load_config'\n")
    os.symlink(outside / "secret.py", repo / "src" / "link.py")
    assert "link.py" not in code_search.grep_files(repo, "token", base=repo)
    assert "link.py" not in code_search.glob_files(repo, "*.py", base=repo)


def test_search_tools_are_safe_only_inside_workdir(repo):
    from app.services.agent_service import classify_risk

    wd = str(repo)
    assert classify_risk("grep", {"pattern": "x"}, wd) == "safe"
    assert classify_risk("glob", {"pattern": "*.py", "path": "src"}, wd) == "safe"
    assert classify_risk("grep", {"pattern": "x", "path": "/etc"}, wd) == "risky"
    assert classify_risk("glob", {"pattern": "*", "path": ".."}, wd) == "risky"
    assert classify_risk("grep", {"pattern": "x"}, None) == "risky"


def test_tools_have_native_schemas():
    from app.services.agent_service import TOOLS, _params_from_description

    grep = _params_from_description(TOOLS["grep"]["description"])
    assert grep["required"] == ["pattern"]
    assert set(grep["properties"]) == {"pattern", "path", "glob", "ignore_case"}
    assert grep["properties"]["ignore_case"] == {"type": "boolean"}
    glob = _params_from_description(TOOLS["glob"]["description"])
    assert glob["required"] == ["pattern"] and set(glob["properties"]) == {"pattern", "path"}
