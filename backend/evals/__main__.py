"""Zenith evals: measure routing, retrieval and agent task success on *your*
installed models, against your local Ollama.

    python -m evals                      # all suites
    python -m evals routing rag          # pick suites
    python -m evals agent --model qwen2.5-coder:7b --repeat 3
    python -m evals --json results.json  # also write a machine-readable report

Runs against a throwaway data directory, never your real Zenith data.
See evals/README.md for what each suite measures and how to read it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
# Isolate from the user's real data before anything imports app.config.
os.environ["ZENITH_DATA_DIR"] = tempfile.mkdtemp(prefix="zenith-evals-")


@dataclass
class SuiteResult:
    name: str
    passed: int = 0
    total: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    seconds: float = 0.0
    note: str = ""

    @property
    def score(self) -> float:
        return self.passed / self.total if self.total else 0.0


# --- routing ----------------------------------------------------------------------


async def run_routing(_args) -> SuiteResult:
    from app.services.router import ModelRegistry, ModelRouter

    res = SuiteResult("routing")
    registry = ModelRegistry()
    installed = await registry.models(force=True)
    router = ModelRouter(registry=registry)
    for line in (HERE / "data" / "routing.jsonl").read_text().splitlines():
        case = json.loads(line)
        d = await router.decide(text=case["text"])
        # With no model for the intended role installed, falling back to
        # "general" is the correct behaviour, not a miss.
        expected = case["role"] if router._match_capability(case["role"], installed) else "general"  # noqa: SLF001
        ok = d.role == expected
        res.total += 1
        res.passed += ok
        res.details.append({"text": case["text"][:60], "expected": expected, "got": d.role,
                            "model": d.model, "confidence": d.confidence, "ok": ok})
    res.note = f"{len(installed)} models installed"
    return res


# --- rag --------------------------------------------------------------------------


async def run_rag(args) -> SuiteResult:
    from app.db.storage import init_db
    from app.services import rag_service

    init_db()
    res = SuiteResult("rag")
    data = json.loads((HERE / "data" / "rag.json").read_text())
    for name, text in data["documents"].items():
        await asyncio.to_thread(rag_service.index_document, name, text, None, "document")
    st = await asyncio.to_thread(rag_service.status)
    k = int(args.k)
    for q in data["questions"]:
        hits = await asyncio.to_thread(rag_service.retrieve, q["q"], None, k, "document")
        ids = [h["source_id"] for h in hits]
        ok = q["doc"] in ids
        res.total += 1
        res.passed += ok
        res.details.append({"q": q["q"], "expected": q["doc"], "got": ids, "ok": ok})
    res.note = f"mode={st['mode']}, embedding={st['embedding_model']}, recall@{k}"
    return res


# --- agent ------------------------------------------------------------------------


@dataclass
class AgentTask:
    name: str
    prompt: str
    setup: Callable[[Path], None]
    verify: Callable[[Path], bool]


def _write(files: dict[str, str]) -> Callable[[Path], None]:
    def setup(d: Path) -> None:
        for rel, content in files.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(content)
    return setup


def _pytest_passes(d: Path) -> bool:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", str(d)], cwd=d, capture_output=True).returncode == 0


AGENT_TASKS = [
    AgentTask("create-file", "Create a file named hello.txt containing exactly the text: hello world",
              _write({}), lambda d: (d / "hello.txt").exists() and (d / "hello.txt").read_text().strip() == "hello world"),
    AgentTask("edit-config", "In settings.ini, change the port from 8000 to 9090. Don't change anything else.",
              _write({"settings.ini": "[server]\nhost = 127.0.0.1\nport = 8000\n"}),
              lambda d: (d / "settings.ini").read_text() == "[server]\nhost = 127.0.0.1\nport = 9090\n"),
    AgentTask("fix-bug", "The tests in test_calc.py fail. Fix calc.py so they pass. Run the tests to check.",
              _write({"calc.py": "def add(a, b):\n    return a - b\n",
                      "test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"}),
              _pytest_passes),
    AgentTask("count-lines", "How many lines does data.csv have, including the header? Write just the number to answer.txt.",
              _write({"data.csv": "id,name\n" + "".join(f"{i},n{i}\n" for i in range(17))}),
              lambda d: (d / "answer.txt").exists() and (d / "answer.txt").read_text().strip() == "18"),
    AgentTask("rename-function", "Rename the function `compute` to `compute_total` in utils.py and update its caller in main.py.",
              _write({"utils.py": "def compute(xs):\n    return sum(xs)\n",
                      "main.py": "from utils import compute\n\nprint(compute([1, 2, 3]))\n"}),
              lambda d: subprocess.run([sys.executable, "main.py"], cwd=d, capture_output=True, text=True).stdout.strip() == "6"
              and "compute_total" in (d / "utils.py").read_text() and "def compute(" not in (d / "utils.py").read_text()),
]


async def run_agent(args) -> SuiteResult:
    from app.core.config import settings
    from app.db import storage
    from app.db.storage import init_db
    from app.services import agent_service

    init_db()
    settings.update({"agent_enabled": True, "agent_mode": "full", "agent_max_iterations": int(args.max_steps),
                     "memory_enabled": False, "recall_enabled": False, "folder_recall_enabled": False,
                     "notes_todos_context_enabled": False, "agent_sandbox": "docker" if args.sandbox else "off"})
    model = args.model or await _default_model("code")
    res = SuiteResult("agent", note=f"model={model}, repeat={args.repeat}, max_steps={args.max_steps}")
    for task in AGENT_TASKS:
        for attempt in range(int(args.repeat)):
            work = Path(tempfile.mkdtemp(prefix=f"zenith-eval-{task.name}-"))
            task.setup(work)
            conv = storage.create_conversation(f"eval {task.name}")["id"]
            storage.set_conversation_workdir(conv, str(work))
            t0 = time.monotonic()
            steps, error = 0, None
            try:
                async for ev in agent_service.run_agent_turn(conv, task.prompt, [], model_override=model):
                    if ev["type"] == "tool_call":
                        steps += 1
                    elif ev["type"] == "error":
                        error = ev["message"]
            except Exception as exc:  # a crashing loop is a failed task, not a crashed eval
                error = str(exc)
            try:
                ok = bool(task.verify(work)) and error is None
            except Exception:
                ok = False
            res.total += 1
            res.passed += ok
            res.details.append({"task": task.name, "attempt": attempt + 1, "ok": ok, "steps": steps,
                                "seconds": round(time.monotonic() - t0, 1), "error": error})
    return res


async def _default_model(role: str) -> str:
    from app.services.router import ModelRegistry, ModelRouter

    reg = ModelRegistry()
    installed = await reg.models(force=True)
    model = ModelRouter(registry=reg)._match_capability(role, installed) or ModelRouter(registry=reg)._match_capability("general", installed)  # noqa: SLF001
    if not model:
        raise SystemExit("No suitable model installed — `ollama pull qwen2.5-coder:7b` (or pass --model).")
    return model


SUITES = {"routing": run_routing, "rag": run_rag, "agent": run_agent}


def _print(res: SuiteResult, verbose: bool) -> None:
    print(f"\n== {res.name}: {res.passed}/{res.total} ({res.score:.0%}) in {res.seconds:.1f}s  [{res.note}]")
    for d in res.details:
        if verbose or not d.get("ok"):
            print("   ", "PASS" if d.get("ok") else "FAIL", {k: v for k, v in d.items() if k != "ok"})


async def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m evals", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("suites", nargs="*", help=f"any of: {', '.join(SUITES)} (default: all)")
    ap.add_argument("--model", help="agent suite: model to drive the agent (default: best installed code model)")
    ap.add_argument("--repeat", default=1, help="agent suite: attempts per task (small models are noisy)")
    ap.add_argument("--max-steps", default=15, help="agent suite: tool-call budget per task")
    ap.add_argument("--sandbox", action="store_true", help="agent suite: run commands in the docker sandbox")
    ap.add_argument("-k", default=3, help="rag suite: top-k for recall@k")
    ap.add_argument("--json", help="write a JSON report here")
    ap.add_argument("-v", "--verbose", action="store_true", help="show passing cases too")
    args = ap.parse_args()
    unknown = [s for s in args.suites if s not in SUITES]
    if unknown:
        ap.error(f"unknown suite(s): {', '.join(unknown)}")

    from app.services.ollama_client import OllamaClient, OllamaError

    try:
        await OllamaClient().list_models()
    except OllamaError as exc:
        print(f"Can't reach Ollama: {exc}")
        return 2

    results = []
    for name in args.suites or list(SUITES):
        t0 = time.monotonic()
        res = await SUITES[name](args)
        res.seconds = time.monotonic() - t0
        _print(res, args.verbose)
        results.append(res)
    if args.json:
        Path(args.json).write_text(json.dumps([{**r.__dict__, "score": r.score} for r in results], indent=2))
        print(f"\nReport written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
