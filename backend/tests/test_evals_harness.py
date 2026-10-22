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
    }
    for task in AGENT_TASKS:
        d = tmp_path / task.name
        d.mkdir()
        task.setup(d)
        assert not task.verify(d), f"{task.name}: unsolved setup already passes"
        for rel, content in solutions[task.name].items():
            (d / rel).write_text(content)
        assert task.verify(d), f"{task.name}: reference solution rejected"
