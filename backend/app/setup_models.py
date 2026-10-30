"""First-run model setup: detect this machine's RAM/GPU and pull a starter
set of Ollama models that will actually run well on it.

    python -m app.setup_models            # show the plan, ask before pulling
    python -m app.setup_models --yes      # pull without asking (install.sh --yes)
    python -m app.setup_models --dry-run  # just print the plan

The plan is the largest *comfortable* fit (see hardware_service._fit) for a
chat model and a code model, plus nomic-embed-text so document search runs
in hybrid (vector + keyword) mode. Models already installed are skipped.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

EMBEDDING_MODEL = "nomic-embed-text"
_FIT_ORDER = {"comfortable": 0, "tight": 1, "unknown": 2, "will_struggle": 3}


def plan(hardware: dict, installed: list[str], cookbook: list[dict], fit) -> list[dict]:
    """Pure: pick at most one model per role (general, code) plus the
    embedding model. Prefers 'comfortable', then 'tight'; among equal fits,
    the biggest (most capable) one."""
    budget = hardware["gpu"]["vram_gb"] if hardware.get("gpu") and hardware["gpu"].get("vram_gb") else hardware.get("ram_gb")
    have = {m.split(":")[0] for m in installed} | set(installed)
    picks: list[dict] = []
    for role in ("general", "code"):
        candidates = [
            {**m, "fit": fit(m.get("params_b"), budget)} for m in cookbook if m.get("role") == role
        ]
        candidates = [c for c in candidates if c["fit"] in ("comfortable", "tight")]
        if not candidates:
            continue
        candidates.sort(key=lambda c: (_FIT_ORDER[c["fit"]], -(c.get("params_b") or 0)))
        best = candidates[0]
        already = [m for m in installed if m.split(":")[0] == best["name"].split(":")[0]]
        picks.append({"role": role, "name": best["name"], "fit": best["fit"],
                      "params_b": best.get("params_b"), "installed": bool(already)})
    picks.append({"role": "embedding", "name": EMBEDDING_MODEL, "fit": "comfortable", "params_b": 0.14,
                  "installed": EMBEDDING_MODEL in have})
    return picks


def _installed() -> list[str]:
    try:
        out = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=20, check=True).stdout
    except Exception:
        return []
    return [line.split()[0] for line in out.splitlines()[1:] if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="pull without asking")
    ap.add_argument("--dry-run", action="store_true", help="print the plan only")
    args = ap.parse_args(argv)

    from app.services.hardware_service import COOKBOOK, _fit, detect_hardware

    hw = detect_hardware()
    gpu = hw.get("gpu")
    print(f"RAM: {hw.get('ram_gb')} GB · CPU cores: {hw.get('cpu_cores')} · "
          f"GPU: {gpu.get('name') + ' (' + str(gpu.get('vram_gb')) + ' GB VRAM)' if gpu else 'none detected (CPU inference)'}")
    if not shutil.which("ollama"):
        print("Ollama isn't installed — get it from https://ollama.com, then re-run this.")
        return 1
    picks = plan(hw, _installed(), COOKBOOK, _fit)
    print("\nRecommended starter models for this machine:")
    for p in picks:
        status = "already installed" if p["installed"] else "to pull"
        print(f"  {p['role']:<10} {p['name']:<28} fit: {p['fit']:<12} {status}")
    todo = [p for p in picks if not p["installed"]]
    if not todo:
        print("\nAll set — nothing to pull.")
        return 0
    if args.dry_run:
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("\nNot a terminal; re-run with --yes to pull.")
            return 0
        if input(f"\nPull {len(todo)} model(s) now? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            return 0
    failed = 0
    for p in todo:
        print(f"\n==> ollama pull {p['name']}")
        failed += subprocess.run(["ollama", "pull", p["name"]]).returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
