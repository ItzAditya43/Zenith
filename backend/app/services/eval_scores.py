"""Agent eval scores per model, written by `python -m evals agent` and shown
in Settings → Models ("agent 4/5"), so model picks rest on measured results
on this machine instead of parameter counts."""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.core.config import data_dir


def _path() -> Path:
    return data_dir() / "eval_scores.json"


def load() -> dict[str, dict]:
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(model: str, passed: int, total: int) -> None:
    scores = load()
    scores[model] = {"passed": passed, "total": total, "at": time.time()}
    _path().write_text(json.dumps(scores, indent=2))
