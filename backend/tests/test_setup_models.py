"""First-run model plan (app.setup_models.plan)."""
from __future__ import annotations

from app.services.hardware_service import COOKBOOK, _fit
from app.setup_models import plan


def _names(picks):
    return {p["role"]: p["name"] for p in picks}


def test_small_laptop_gets_small_models():
    picks = plan({"ram_gb": 8, "gpu": None}, [], COOKBOOK, _fit)
    by_role = {p["role"]: p for p in picks}
    assert by_role["general"]["fit"] in ("comfortable", "tight")
    assert (by_role["general"]["params_b"] or 0) <= 8
    assert by_role["embedding"]["name"] == "nomic-embed-text"


def test_big_gpu_prefers_bigger_models_than_cpu_only():
    small = {p["role"]: p for p in plan({"ram_gb": 8, "gpu": None}, [], COOKBOOK, _fit)}
    big = {p["role"]: p for p in plan({"ram_gb": 64, "gpu": {"vram_gb": 24}}, [], COOKBOOK, _fit)}
    assert (big["general"]["params_b"] or 0) >= (small["general"]["params_b"] or 0)
    assert (big["code"]["params_b"] or 0) >= (small["code"]["params_b"] or 0)


def test_installed_models_are_marked():
    first = plan({"ram_gb": 16, "gpu": None}, [], COOKBOOK, _fit)
    general = next(p for p in first if p["role"] == "general")["name"]
    again = plan({"ram_gb": 16, "gpu": None}, [general, "nomic-embed-text:latest"], COOKBOOK, _fit)
    flags = {p["role"]: p["installed"] for p in again}
    assert flags["general"] and flags["embedding"]


def test_tiny_machine_still_gets_embedding_model():
    picks = plan({"ram_gb": 1, "gpu": None}, [], COOKBOOK, _fit)
    assert [p["role"] for p in picks][-1] == "embedding"
