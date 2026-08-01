"""
Central configuration for Zenith.

Everything here can be overridden by environment variables or by editing
`data/config.json` at runtime through the Settings panel in the UI.
"""
import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _resolve_data_dir() -> Path:
    """Resolve the data directory at access time so monkeypatched
    `CORTEX_DATA_DIR` env vars in tests take effect."""
    env = os.environ.get("CORTEX_DATA_DIR")
    if env:
        return Path(env)
    return BASE_DIR / "data"


def data_dir() -> Path:
    d = _resolve_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload_dir() -> Path:
    p = data_dir() / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "zenith.db"


def config_path() -> Path:
    return data_dir() / "config.json"


# Module-level constants — set at import time from the current env.
# Most call sites can use the functions above for late binding. These
# exist for `from app.core.config import DB_PATH` style imports.
DB_PATH = db_path()
CONFIG_PATH = config_path()
UPLOAD_DIR = upload_dir()
DATA_DIR = data_dir()


def refresh_paths() -> None:
    """Re-evaluate DB_PATH / DATA_DIR / etc. from the current
    `CORTEX_DATA_DIR` env var. Useful for tests that set the env var
    after config.py was first imported. Call this from the test fixture
    right after `monkeypatch.setenv('CORTEX_DATA_DIR', ...)`."""
    global DB_PATH, CONFIG_PATH, UPLOAD_DIR, DATA_DIR
    DB_PATH = db_path()
    CONFIG_PATH = config_path()
    UPLOAD_DIR = upload_dir()
    DATA_DIR = data_dir()


DEFAULT_CONFIG: dict[str, Any] = {
    # --- Ollama ---
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
    # Fallback when the chosen model fails mid-stream (Tier 1 #5).
    # Resolved by capability role: a role name (e.g. "general") or an
    # exact model name. Default role-based fallback.
    "fallback_model": os.environ.get("CORTEX_FALLBACK_MODEL", "general"),
    # --- STT / TTS ---
    "whisper_model_size": os.environ.get("WHISPER_MODEL_SIZE", "small"),
    "whisper_device": os.environ.get("WHISPER_DEVICE", "cpu"),
    "whisper_compute_type": os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
    "tts_engine": os.environ.get("TTS_ENGINE", "piper"),  # "piper" | "pyttsx3"
    "piper_voice": os.environ.get("PIPER_VOICE", "en_US-lessac-medium"),
    "piper_voices_dir": os.environ.get("PIPER_VOICES_DIR", str(data_dir() / "piper_voices")),
    # --- Streaming behaviour ---
    "sse_heartbeat_seconds": 15,
    "stream_idle_timeout_seconds": 120,
    # --- Attachments ---
    "upload_orphan_ttl_seconds": 24 * 3600,
    "upload_sweep_interval_seconds": 30 * 60,
    "upload_max_bytes": 200 * 1024 * 1024,
    # --- Router ---
    "max_context_messages": 24,
    "default_context_window": 8192,
    "router_confidence_threshold": 0.55,
    "router_show_confidence": True,
    # --- Auth (off by default — see Tier1 #8) ---
    "auth_enabled": False,
    "auth_shared_secret": "",
    # --- Image generation (local Stable Diffusion server, off until set) ---
    "image_gen_url": "",             # e.g. http://localhost:7860 (AUTOMATIC1111 --api)
    "image_gen_steps": 20,
    "image_gen_size": 512,
    "image_gen_timeout_seconds": 180,
    # --- Email (IMAP/SMTP over your own account — no third-party mail API,
    # runs the same "everything stays on your machine" way as the rest of
    # the app). Off until configured. Credentials are stored in plaintext
    # in config.json, same trust model as the rest of local settings — this
    # is a personal-use app, not a multi-tenant one. Use an app password,
    # not your real account password, where the provider supports it. ---
    "email_enabled": False,
    "email_imap_host": "",
    "email_imap_port": 993,
    "email_smtp_host": "",
    "email_smtp_port": 587,
    "email_username": "",
    "email_password": "",
    "email_fetch_count": 20,
    # --- App-level passcode lock (gates the UI/API on a shared machine —
    # not at-rest encryption; the SQLite file itself is still readable by
    # anyone with filesystem access). Off until the user sets a passcode. ---
    "lock_enabled": False,
    "lock_pass_hash": "",
    "cors_allow_origins": [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        # The desktop app's webview — Tauri v2 serves the frontend from its
        # own custom scheme, not localhost, so without these the bundled
        # backend silently CORS-blocks every request from the installed app.
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    # Multi-device access: when on, also accept requests from private-LAN and
    # Tailscale (*.ts.net) origins so you can open Zenith from a phone/laptop
    # on the same network. Off by default — it widens who can reach the API,
    # so pair it with the passcode lock or shared-secret auth. See MULTIDEVICE.md.
    "cors_allow_lan": False,
    # --- Operational ---
    "log_level": "INFO",
    "request_timeout_seconds": 600,
    "prewarm_model_on_startup": False,
    # --- Agent tool use (bash/files/web) ---
    "agent_enabled": False,          # master switch — off until you opt in
    "agent_mode": "manual",          # "manual" | "semi" | "full"
    "agent_max_iterations": 40,      # tool-call rounds before forcing a final answer
    "agent_command_timeout_seconds": 60,
    "agent_output_max_chars": 4000,  # cap per tool result fed back to the model
    "agent_approval_timeout_seconds": 600,  # auto-deny if you don't respond
    "agent_subagent_max_iterations": 8,  # step budget for a spawn_subagent delegation
    "agent_check_command": "",       # e.g. "pytest -q" or "npm test" — run_checks default
    "agent_auto_check": False,       # auto-run the check command after each file edit
    "agent_check_timeout_seconds": 180,  # tests/lint can be slower than a plain command
    # --- Scheduled/recurring turns ---
    "schedule_check_interval_seconds": 60,  # how often the scanner checks for due schedules
    # --- Folder watcher ---
    "folder_scan_interval_seconds": 600,  # 10 min between background re-scans
    "folder_recall_enabled": True,
    "folder_recall_top_k": 3,
    # --- Council of models ---
    "council_models": [],  # model names to query together when Council mode is on
    # --- Deep Research (multi-step search/read/synthesize) ---
    "research_max_iterations": 10,
    # --- Web search / URL reading ---
    "web_search_max_results": 5,
    "web_fetch_max_chars": 4000,
    "web_fetch_timeout_seconds": 8,
    "web_fetch_max_urls_per_turn": 3,
    # --- Personal assistant / memory ---
    "memory_enabled": True,          # extract + inject long-term user facts
    "memory_max_items": 200,
    "memory_recall_top_k": 12,       # above this many stored memories, inject only the most relevant instead of all
    "system_prompt": "",             # user persona / standing instructions
    "recall_enabled": True,          # cross-conversation retrieval
    "recall_top_k": 3,
    # --- RAG / long-term memory ---
    "rag_enabled": True,
    "rag_chunk_chars": 1200,
    "rag_chunk_overlap": 200,
    "rag_top_k": 5,
    "rag_embedding_model": "",  # blank => use the auto-classified "embedding" role
    # --- Voice (Tier 3) ---
    "voice_chunk_sentences": True,
    # --- Document OCR fallback (Tier 4) ---
    "doc_ocr_fallback": False,  # off by default — requires tesseract
    "doc_ocr_min_text_chars": 40,
    # --- Multimodal (Tier 4) ---
    "video_frame_sample_seconds": 4,
    "video_max_frames": 8,
    "video_scene_threshold": 0.3,
    # --- Document chunking ---
    "doc_chunk_chars": 6000,
    # --- Attachment TTL (also drives the sweeper) ---
    "attachment_ttl_hours": 72,
    # --- Frontend / experimental ---
    "ui_experimental": False,
}


def _load() -> dict[str, Any]:
    cp = config_path()
    if cp.exists():
        try:
            stored = json.loads(cp.read_text())
            merged = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
            merged.update({k: v for k, v in stored.items() if k in merged})
            # deep-merge nested dicts so new default keys aren't lost on upgrade
            for key in ("capability_keywords", "model_overrides"):
                if key in stored and isinstance(stored[key], dict):
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
        config_path().write_text(json.dumps(self._data, indent=2))

    def reload(self) -> None:
        """Re-read `config.json` from disk into memory.

        Useful after the file was edited out-of-band (Settings UI,
        tests with monkeypatched CORTEX_DATA_DIR, etc.)."""
        self._data = _load()

    def set(self, key: str, value: Any) -> None:
        """Convenience: set one key and persist. Lets tests / callers
        mutate a single field without rebuilding the whole patch dict."""
        self._data[key] = value
        self.save()


settings = Settings()