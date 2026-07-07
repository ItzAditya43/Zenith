"""
Central configuration for Cortex.

Everything here can be overridden by environment variables or by editing
`data/config.json` at runtime through the Settings panel in the UI.
"""
import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "cortex.db"
CONFIG_PATH = DATA_DIR / "config.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG: dict[str, Any] = {
    "ollama_host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
    # Capability keywords used to auto-classify models pulled from
    # `GET /api/tags`. First matching keyword wins. Order matters.
    # Users can add/rename/reorder these from Settings without touching code.
    "capability_keywords": {
        "vision": ["llava", "bakllava", "moondream", "llama3.2-vision", "minicpm-v", "qwen2-vl", "qwen2.5vl"],
        "code": ["coder", "codellama", "starcoder", "codegemma", "deepseek-coder"],
        "reasoning": ["deepseek-r1", "qwq", "o1", "reasoner"],
        "embedding": ["embed", "nomic-embed", "bge", "mxbai-embed"],
        "small_fast": ["phi3", "phi-3", "gemma2:2b", "qwen2.5:0.5b", "qwen2.5:1.5b", "tinyllama"],
        "general": ["llama3", "llama2", "mistral", "gemma", "qwen", "command-r"],
    },
    # Explicit user overrides: {"role": "exact-model-name"} always wins over
    # keyword auto-detection. Populated from the Settings UI.
    "model_overrides": {
        "vision": None,
        "code": None,
        "reasoning": None,
        "embedding": None,
        "small_fast": None,
        "general": None,
    },
    # STT / TTS
    "whisper_model_size": os.environ.get("WHISPER_MODEL_SIZE", "small"),
    "whisper_device": os.environ.get("WHISPER_DEVICE", "cpu"),
    "whisper_compute_type": os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
    "tts_engine": os.environ.get("TTS_ENGINE", "piper"),  # "piper" | "pyttsx3"
    "piper_voice": os.environ.get("PIPER_VOICE", "en_US-lessac-medium"),
    "piper_voices_dir": os.environ.get("PIPER_VOICES_DIR", str(DATA_DIR / "piper_voices")),
    # Router behaviour
    "max_context_messages": 24,
    "video_frame_sample_seconds": 4,
    "video_max_frames": 8,
    "doc_chunk_chars": 6000,
}


def _load() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text())
            merged = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
            merged.update({k: v for k, v in stored.items() if k in merged})
            # deep-merge nested dicts so new default keys aren't lost on upgrade
            for key in ("capability_keywords", "model_overrides"):
                if key in stored:
                    merged[key] = {**merged[key], **stored[key]}
            return merged
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


class Settings:
    """Thin mutable wrapper so the whole app can share live config state."""

    def __init__(self) -> None:
        self._data = _load()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def all(self) -> dict[str, Any]:
        return self._data

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        for key in ("capability_keywords", "model_overrides"):
            if key in patch and isinstance(patch[key], dict):
                self._data.setdefault(key, {})
                self._data[key].update(patch[key])
                patch = {k: v for k, v in patch.items() if k != key}
        self._data.update(patch)
        self.save()
        return self._data

    def save(self) -> None:
        CONFIG_PATH.write_text(json.dumps(self._data, indent=2))


settings = Settings()
