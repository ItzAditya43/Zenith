"""Repo map (repo_map.build) and its injection into the agent's prompt."""
from __future__ import annotations

import pytest

from app.services import repo_map


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "main.py").write_text(
        "import os\n\n"
        "class Server(Base):\n"
        "    def __init__(self, port: int = 80):\n        pass\n"
        "    async def start(self):\n        pass\n"
        "    def _private(self):\n        pass\n\n"
        "def run(argv, *, debug=False):\n    def inner():\n        pass\n"
    )
    (tmp_path / "pkg" / "ui.tsx").write_text(
        "export function Button({ label }: Props) {\n  const local = () => 1;\n  return null;\n}\n"
        "export const useThing = (id: string) => {\n};\n"
        "interface Props { label: string }\n"
        "export default class Store extends Base {\n}\n"
    )
    (tmp_path / "pkg" / "lib.go").write_text(
        "package lib\n\ntype Client struct {\n}\n\nfunc (c *Client) Get(url string) error {\n}\n\nfunc New() *Client {\n}\n"
    )
    (tmp_path / "pkg" / "core.rs").write_text(
        "pub struct Engine {}\n\nimpl Engine {\n    pub fn run(&self) -> u8 {\n    }\n}\n\nfn helper() {}\n"
    )
    (tmp_path / "tests" / "test_main.py").write_text("def test_run():\n    pass\n")
    (tmp_path / "notes.md").write_text("# not code\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("function vendored() {}\n")
    repo_map._cache.clear()
    return tmp_path


def test_python_outline_has_signatures_and_public_methods(repo):
    out = repo_map.build(str(repo), 10_000)
    assert "main.py\n  class Server(Base)\n    def __init__(self, port: int=80)\n    async def start(self)\n" in out
    assert "  def run(argv, *, debug=False)" in out
    assert "_private" not in out and "inner" not in out


def test_other_languages_are_outlined(repo):
    out = repo_map.build(str(repo), 10_000)
    for expected in (
        "  export function Button({ label }: Props)",
        "  export const useThing = (id: string) =>",
        "  interface Props",
        "  export default class Store extends Base",
        "  type Client struct",
        "  func (c *Client) Get(url string)",
        "  func New()",
        "  pub struct Engine",
        "  impl Engine",
        "    pub fn run(&self)",
        "  fn helper()",
    ):
        assert expected in out, expected


def test_skips_non_source_and_noise_dirs(repo):
    out = repo_map.build(str(repo), 10_000)
    assert "notes.md" not in out and "node_modules" not in out and "vendored" not in out


def test_app_code_is_listed_before_tests(repo):
    lines = repo_map.build(str(repo), 10_000).splitlines()
    assert lines[0] == "main.py"
    assert lines.index("tests/test_main.py") > lines.index("pkg/ui.tsx")


def test_budget_drops_detail_before_files(repo):
    full = repo_map.build(str(repo), 10_000)
    small = repo_map.build(str(repo), 200)
    assert len(small) <= 200 < len(full)
    for path in ("main.py", "pkg/core.rs", "pkg/lib.go", "pkg/ui.tsx", "tests/test_main.py"):
        assert path in small
    assert "async def start" not in small   # methods are the first detail to go


def test_tiny_budget_truncates_the_file_list(repo):
    for i in range(10):
        (repo / "pkg" / f"module_number_{i}.py").write_text("")
    out = repo_map.build(str(repo), 150)
    assert len(out) <= 150 and "tests/test_main.py" not in out
    assert out.startswith("main.py") and "more source files not listed" in out


def test_broken_python_falls_back_to_regex(repo):
    (repo / "broken.py").write_text("def ok(a, b):\n    return (\n\nclass Half:\n")
    out = repo_map.build(str(repo), 10_000)
    assert "broken.py\n  def ok(a, b)\n  class Half" in out


def test_edits_are_picked_up(repo):
    repo_map.build(str(repo), 10_000)
    (repo / "main.py").write_text("def brand_new_function():\n    pass\n")
    assert "def brand_new_function()" in repo_map.build(str(repo), 10_000)


def test_empty_or_missing_directory_gives_nothing(tmp_path):
    assert repo_map.build(str(tmp_path), 1000) == ""
    assert repo_map.build(str(tmp_path / "nope"), 1000) == ""
