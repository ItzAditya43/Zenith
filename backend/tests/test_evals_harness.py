"""The evals harness itself runs (routing + rag suites against the fake Ollama)."""
from __future__ import annotations

import argparse


async def test_routing_and_rag_suites_run(fake_ollama):
    from app.core.config import settings
    from evals.__main__ import run_rag, run_routing

    settings.update({"rag_embedding_model": "nomic-embed-text"})
    routing = await run_routing(argparse.Namespace())
    assert routing.total == 16 and routing.score >= 0.9
    rag = await run_rag(argparse.Namespace(k=3))
    assert rag.total == 8 and rag.score >= 0.75


def _sh(d, cmd):
    import subprocess

    subprocess.run(cmd, shell=True, cwd=d, check=True)


def test_agent_tasks_verify_their_own_reference_solutions(tmp_path):
    """Each task's verify() must accept a correct solution and reject the setup state."""
    from evals.__main__ import AGENT_TASKS

    solutions = {
        "create-file": {"hello.txt": "hello world\n"},
        "edit-config": {"settings.ini": "[server]\nhost = 127.0.0.1\nport = 9090\n"},
        "fix-bug": {"calc.py": "def add(a, b):\n    return a + b\n"},
        "count-lines": {"answer.txt": "18\n"},
        "rename-function": {"utils.py": "def compute_total(xs):\n    return sum(xs)\n",
                            "main.py": "from utils import compute_total\n\nprint(compute_total([1, 2, 3]))\n"},
        "tdd-slugify": {"text.py": "import re\n\n\ndef slugify(s):\n    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')\n"},
        "multi-file-bug": {"shop/pricing.py": "def apply_discount(total, percent):\n    return total - total * percent / 100\n"},
        "find-raiser": {"answer.txt": "parse_port\n"},
        "git-commit": lambda d: _sh(d, "git add notes.md && git commit -qm 'Update notes'"),
        "git-branch": lambda d: _sh(d, "git switch -qc feature/readme && git add README.md && git commit -qm 'Add readme'"),
        "json-script": {"package.json": '{"name": "shop", "scripts": {"build": "vite build", "lint": "eslint ."}}\n'},
        "write-tests": {"test_stack.py": "import pytest\n\nfrom stack import Stack\n\n\ndef test_push():\n    s = Stack()\n    s.push(1)\n    assert len(s) == 1\n\n\n"
                                         "def test_pop():\n    s = Stack()\n    s.push(2)\n    assert s.pop() == 2\n\n\n"
                                         "def test_empty():\n    with pytest.raises(IndexError):\n        Stack().pop()\n"},
    }
    for task in AGENT_TASKS:
        d = tmp_path / task.name
        d.mkdir()
        task.setup(d)
        assert not task.verify(d), f"{task.name}: unsolved setup already passes"
        sol = solutions[task.name]
        if callable(sol):
            sol(d)
        else:
            for rel, content in sol.items():
                (d / rel).write_text(content)
        assert task.verify(d), f"{task.name}: reference solution rejected"
