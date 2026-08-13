"""Hardware-aware model manager: reads what this machine actually has
(RAM, CPU cores, GPU/VRAM if detectable) with zero extra dependencies —
just /proc, os, and shutil — then scores installed and pullable models
against it so recommendations are grounded in "will this actually run
well here", not a generic leaderboard.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from app.core.logging import get_logger

log = get_logger(__name__)

# A small curated cookbook of well-known Ollama models worth recommending,
# not an exhaustive registry mirror — good general/code/vision picks across
# a range of sizes.
COOKBOOK = [
    # small_fast — quick replies, low-latency, minimal footprint
    {"name": "llama3.2:1b", "params_b": 1, "role": "small_fast", "note": "Tiny — runs anywhere, good for quick replies."},
    {"name": "qwen2.5:0.5b", "params_b": 0.5, "role": "small_fast", "note": "Extremely small — near-instant replies, limited depth."},
    {"name": "gemma2:2b", "params_b": 2, "role": "small_fast", "note": "Small Google model, fast and decent quality for its size."},
    # general — well-rounded chat/assistant models
    {"name": "llama3.2:3b", "params_b": 3, "role": "general", "note": "Solid all-rounder on modest hardware."},
    {"name": "qwen2.5:7b", "params_b": 7, "role": "general", "note": "Strong general + code model at 7B."},
    {"name": "mistral:7b", "params_b": 7, "role": "general", "note": "Fast, capable 7B general model."},
    {"name": "llama3.1:8b", "params_b": 8, "role": "general", "note": "Meta's well-rounded 8B."},
    {"name": "gemma2:9b", "params_b": 9, "role": "general", "note": "Strong mid-size general model from Google."},
    # code — dedicated coding models
    {"name": "qwen2.5-coder:7b", "params_b": 7, "role": "code", "note": "Dedicated coding model."},
    {"name": "codellama:13b", "params_b": 13, "role": "code", "note": "Meta's code-focused model, good at completion + explanation."},
    {"name": "deepseek-coder-v2:16b", "params_b": 16, "role": "code", "note": "MoE coding model, strong at code generation for its footprint."},
    # vision — image understanding
    {"name": "llava:7b", "params_b": 7, "role": "vision", "note": "Image understanding at 7B."},
    {"name": "llava:13b", "params_b": 13, "role": "vision", "note": "Larger LLaVA — better image understanding, more RAM/VRAM."},
    {"name": "qwen2.5vl:7b", "params_b": 7, "role": "vision", "note": "Qwen's vision-language model, strong OCR/document understanding."},
    # reasoning — harder problems, math, multi-step
    {"name": "qwen2.5:14b", "params_b": 14, "role": "reasoning", "note": "Noticeably stronger reasoning at 14B."},
    {"name": "phi4:14b", "params_b": 14, "role": "reasoning", "note": "Microsoft's reasoning-tuned model, punches above its size."},
    {"name": "qwen2.5:32b", "params_b": 32, "role": "reasoning", "note": "High-end reasoning/code, needs real RAM/VRAM."},
    {"name": "llama3.1:70b", "params_b": 70, "role": "reasoning", "note": "Frontier-ish local model — serious hardware only."},
]

# Large models that run on Ollama's own hosted servers, not this machine —
# identified by the ":cloud" tag suffix. These exist specifically to cover
# what local hardware can't: huge reasoning/code models a normal machine
# has no chance of running. Requires an ollama.com account; NOT scored for
# hardware fit (fit is irrelevant — nothing here touches local compute).
# Kept strictly separate from COOKBOOK and only surfaced when the user has
# explicitly opted in via show_cloud_model_suggestions.
CLOUD_COOKBOOK = [
    {
        "name": "qwen3-coder-480b:cloud",
        "role": "code",
        "note": "480B-class coding model — runs on Ollama's servers, not this machine, requires an ollama.com account.",
    },
    {
        "name": "deepseek-v3.1:671b-cloud",
        "role": "reasoning",
        "note": "671B-class frontier reasoning/general model — runs on Ollama's servers, not this machine, requires an ollama.com account.",
    },
    {
        "name": "qwen3:235b-cloud",
        "role": "reasoning",
        "note": "235B-class reasoning model — runs on Ollama's servers, not this machine, requires an ollama.com account.",
    },
    {
        "name": "gpt-oss:120b-cloud",
        "role": "general",
        "note": "120B open-weight general model hosted by Ollama — runs on Ollama's servers, not this machine, requires an ollama.com account.",
    },
    {
        "name": "llama3.1:405b-cloud",
        "role": "general",
        "note": "405B-class general model — runs on Ollama's servers, not this machine, requires an ollama.com account.",
    },
]


def _parse_params_b(model_name: str) -> float | None:
    """Best-effort parameter count in billions from an Ollama tag like
    'qwen2.5:7b' or 'mixtral:8x7b'. Returns None if unparseable."""
    tag = model_name.split(":")[-1].lower()
    moe = re.match(r"(\d+)x(\d+(?:\.\d+)?)b", tag)
    if moe:
        experts, each = int(moe.group(1)), float(moe.group(2))
        # Mixture-of-experts: all experts must fit in memory even though only
        # some activate per token, so size by total params, not active params.
        return experts * each
    single = re.search(r"(\d+(?:\.\d+)?)b", tag)
    if single:
        return float(single.group(1))
    return None


def _detect_ram_gb() -> float | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024 * 1024), 1)
    except Exception as exc:
        log.debug("hardware.ram_detect_failed", error=str(exc))
    return None


def _detect_gpu() -> dict | None:
    """Checks for an NVIDIA or AMD GPU via their CLI tools. Returns None
    (not "no GPU" for certain — just "couldn't detect one") if neither
    tool is present, which is the common case in a container without
    GPU passthrough."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            name, mem = out.stdout.strip().split(",")
            vram_mb = int(re.sub(r"[^\d]", "", mem))
            return {"vendor": "nvidia", "name": name.strip(), "vram_gb": round(vram_mb / 1024, 1)}
    except Exception:
        pass
    try:
        out = subprocess.run(["rocm-smi", "--showmeminfo", "vram"], capture_output=True, text=True, timeout=3)
        if out.returncode == 0 and out.stdout.strip():
            return {"vendor": "amd", "name": "AMD GPU", "vram_gb": None}
    except Exception:
        pass
    return None


def detect_hardware() -> dict:
    ram_gb = _detect_ram_gb()
    cpu_cores = os.cpu_count()
    gpu = _detect_gpu()
    disk_free_gb = None
    try:
        disk_free_gb = round(shutil.disk_usage("/").free / (1024 ** 3), 1)
    except Exception as exc:
        log.debug("hardware.disk_detect_failed", error=str(exc))
    return {"ram_gb": ram_gb, "cpu_cores": cpu_cores, "gpu": gpu, "disk_free_gb": disk_free_gb}


def _fit(params_b: float | None, budget_gb: float | None) -> str:
    """Rough q4-quantized footprint is ~0.65GB per billion params, plus
    ~1.5GB of runtime/context overhead. This is a heuristic, not a promise —
    actual usage varies by quantization and context length."""
    if params_b is None or budget_gb is None:
        return "unknown"
    est_gb = params_b * 0.65 + 1.5
    if est_gb <= budget_gb * 0.6:
        return "comfortable"
    if est_gb <= budget_gb * 0.9:
        return "tight"
    return "will_struggle"


def score_models(installed: list[str], include_cloud: bool = False) -> dict:
    hw = detect_hardware()
    budget = (hw["gpu"]["vram_gb"] if hw["gpu"] and hw["gpu"].get("vram_gb") else hw["ram_gb"])
    scored_installed = []
    for name in installed:
        params_b = _parse_params_b(name)
        scored_installed.append({
            "name": name, "params_b": params_b, "fit": _fit(params_b, budget),
        })
    installed_set = {n.split(":")[0] for n in installed}
    recommended = [
        {**m, "fit": _fit(m["params_b"], budget)}
        for m in COOKBOOK
        if m["name"].split(":")[0] not in installed_set
    ]
    # Best fit first, then smaller (cheaper to try) first.
    order = {"comfortable": 0, "tight": 1, "unknown": 2, "will_struggle": 3}
    recommended.sort(key=lambda m: (order[m["fit"]], m["params_b"] or 0))
    result = {
        "hardware": hw,
        "budget_gb": budget,
        "installed": scored_installed,
        "recommended": recommended[:6],
    }
    if include_cloud:
        # No hardware fit scoring here on purpose — these never run locally,
        # so a fit rating against local RAM/VRAM would be meaningless (and
        # misleading, since it could read as "supported locally").
        installed_full = set(installed)
        result["cloud_recommended"] = [
            dict(m) for m in CLOUD_COOKBOOK if m["name"] not in installed_full
        ]
    return result
