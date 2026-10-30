"""Pydantic models for request/response bodies.

Adding `model_config = ConfigDict(extra="forbid")` makes the API strict
about unknown fields (returns 422 instead of silently ignoring them).
Enums + `Field` constraints on numeric ranges give us a 422 instead of
silently accepting garbage values (e.g. `whisper_model_size = "garbage"`).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictModel):
    conversation_id: str
    message: str
    attachment_ids: list[str] = []  # ids returned by /api/upload
    web_search: bool = False  # composer "Search" toggle
    agent_mode_on: bool = False  # composer "Agent" toggle
    deep_research: bool = False  # composer "Research" toggle
    edit_of: str | None = None  # branching: id of the user message being replaced
    regenerate_of: str | None = None  # branching: assistant message id to regenerate
    model_override: str | None = None  # skip auto-routing, force this exact installed model


class ConversationCreate(StrictModel):
    title: str = "New chat"
    project_id: str | None = None


class ConversationRename(StrictModel):
    title: str = Field(min_length=1, max_length=200)


WhisperModelSize = Literal["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3"]
TtsEngine = Literal["piper", "pyttsx3"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class ConfigPatch(StrictModel):
    """All fields are optional; only the ones the caller actually
    sends get applied. Unknown fields are rejected (extra='forbid')."""

    ollama_host: str | None = Field(default=None, min_length=1, max_length=500)
    model_overrides: dict[str, str | None] | None = None
    capability_keywords: dict[str, list[str]] | None = None
    whisper_model_size: WhisperModelSize | None = None
    tts_engine: TtsEngine | None = None
    piper_voice: str | None = Field(default=None, min_length=1, max_length=200)
    fallback_model: str | None = Field(default=None, min_length=1, max_length=200)
    auth_enabled: bool | None = None
    auth_shared_secret: str | None = None
    cors_allow_origins: list[str] | None = None
    cors_allow_lan: bool | None = None
    rag_enabled: bool | None = None
    rag_chunk_chars: int | None = Field(default=None, ge=200, le=20_000)
    rag_chunk_overlap: int | None = Field(default=None, ge=0, le=5_000)
    rag_top_k: int | None = Field(default=None, ge=1, le=20)
    rag_rerank_enabled: bool | None = None
    rag_rerank_model: str | None = Field(default=None, max_length=200)
    rag_rerank_pool: int | None = Field(default=None, ge=1, le=50)
    rag_rerank_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    show_cloud_model_suggestions: bool | None = None
    doc_ocr_fallback: bool | None = None
    video_scene_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    router_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    log_level: LogLevel | None = None
    request_timeout_seconds: int | None = Field(default=None, ge=5, le=7200)
    prewarm_model_on_startup: bool | None = None
    sse_heartbeat_seconds: int | None = Field(default=None, ge=0, le=120)
    upload_max_bytes: int | None = Field(default=None, ge=1_024, le=5 * 1024 * 1024 * 1024)
    max_context_messages: int | None = Field(default=None, ge=1, le=200)
    attachment_ttl_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    voice_chunk_sentences: bool | None = None
    ui_experimental: bool | None = None
    memory_enabled: bool | None = None
    memory_max_items: int | None = Field(default=None, ge=10, le=2000)
    memory_recall_top_k: int | None = Field(default=None, ge=1, le=100)
    notes_todos_context_enabled: bool | None = None
    digest_enabled: bool | None = None
    digest_interval_hours: int | None = Field(default=None, ge=1, le=168)
    system_prompt: str | None = Field(default=None, max_length=8000)
    recall_enabled: bool | None = None
    recall_top_k: int | None = Field(default=None, ge=1, le=10)
    web_search_backend: Literal["duckduckgo", "searxng"] | None = None
    searxng_url: str | None = Field(default=None, max_length=500)
    web_search_max_results: int | None = Field(default=None, ge=1, le=10)
    web_fetch_max_chars: int | None = Field(default=None, ge=500, le=20_000)
    web_fetch_timeout_seconds: int | None = Field(default=None, ge=2, le=60)
    web_fetch_max_urls_per_turn: int | None = Field(default=None, ge=0, le=10)
    agent_enabled: bool | None = None
    agent_mode: Literal["manual", "semi", "full", "plan"] | None = None
    agent_max_iterations: int | None = Field(default=None, ge=1, le=200)
    agent_command_timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    agent_output_max_chars: int | None = Field(default=None, ge=500, le=20_000)
    agent_approval_timeout_seconds: int | None = Field(default=None, ge=30, le=3600)
    agent_subagent_max_iterations: int | None = Field(default=None, ge=1, le=50)
    agent_check_command: str | None = Field(default=None, max_length=500)
    agent_auto_check: bool | None = None
    agent_check_timeout_seconds: int | None = Field(default=None, ge=5, le=1800)
    route_to_cloud_models: bool | None = None
    router_semantic_margin: float | None = Field(default=None, ge=0, le=0.5)
    thinking_mode: Literal["auto", "on", "off"] | None = None
    embedding_timeout_seconds: int | None = Field(default=None, ge=10, le=900)
    agent_sandbox: Literal["off", "docker"] | None = None
    agent_sandbox_image: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")
    agent_sandbox_network: Literal["none", "bridge"] | None = None
    agent_sandbox_memory: str | None = Field(default=None, pattern=r"^\d+[kmg]?$")
    agent_sandbox_cpus: str | None = Field(default=None, pattern=r"^\d+(\.\d+)?$")
    image_gen_url: str | None = Field(default=None, max_length=500)
    image_gen_steps: int | None = Field(default=None, ge=1, le=150)
    image_gen_size: int | None = Field(default=None, ge=128, le=2048)
    image_gen_timeout_seconds: int | None = Field(default=None, ge=10, le=1800)
    research_max_iterations: int | None = Field(default=None, ge=2, le=30)
    council_models: list[str] | None = Field(default=None, max_length=6)
    folder_scan_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    folder_recall_enabled: bool | None = None
    folder_recall_top_k: int | None = Field(default=None, ge=1, le=10)
    schedule_check_interval_seconds: int | None = Field(default=None, ge=15, le=3600)
    email_enabled: bool | None = None
    email_imap_host: str | None = Field(default=None, max_length=255)
    email_imap_port: int | None = Field(default=None, ge=1, le=65535)
    email_smtp_host: str | None = Field(default=None, max_length=255)
    email_smtp_port: int | None = Field(default=None, ge=1, le=65535)
    email_username: str | None = Field(default=None, max_length=255)
    email_password: str | None = Field(default=None, max_length=500)
    email_fetch_count: int | None = Field(default=None, ge=1, le=200)
    notify_ntfy_enabled: bool | None = None
    notify_ntfy_url: str | None = Field(default=None, min_length=1, max_length=500)
    notify_ntfy_topic: str | None = Field(default=None, max_length=200)
    notify_event_types: list[str] | None = Field(default=None, max_length=10)
    wake_word_enabled: bool | None = None
    wake_word_phrase: str | None = Field(default=None, min_length=1, max_length=100)


class MemoryCreate(StrictModel):
    content: str = Field(min_length=1, max_length=300)
    category: str = Field(default="fact", max_length=40)


class MemoryToggle(StrictModel):
    enabled: bool


class WebhookCreate(StrictModel):
    url: str = Field(min_length=1, max_length=500)
    event_types: list[str] = Field(min_length=1, max_length=10)


class AutomationRuleCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    trigger_type: str = Field(min_length=1, max_length=60)
    trigger_config: dict = Field(default_factory=dict)
    action_type: str = Field(min_length=1, max_length=20)
    action_config: dict = Field(default_factory=dict)


class PersonaCreate(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    system_prompt: str = Field(min_length=1, max_length=8000)
    icon: str | None = Field(default=None, max_length=8)


class PersonaUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    icon: str | None = Field(default=None, max_length=8)


class ConversationPersonaSet(StrictModel):
    persona_id: str | None = None


class ConversationWorkdirSet(StrictModel):
    workdir: str | None = Field(default=None, max_length=1000)


class CouncilRequest(StrictModel):
    conversation_id: str
    message: str
    attachment_ids: list[str] = []
    models: list[str] = Field(min_length=1, max_length=6)


class WatchedFolderCreate(StrictModel):
    path: str = Field(min_length=1, max_length=1000)
    extensions: str | None = Field(default=None, max_length=200)


class WatchedFolderToggle(StrictModel):
    enabled: bool


class ScheduleCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=4000)
    mode: Literal["chat", "research"] = "chat"
    interval_minutes: int = Field(ge=1, le=43200)


class ScheduleToggle(StrictModel):
    enabled: bool


class MCPServerCreate(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    command: str = Field(min_length=1, max_length=500)
    args: list[str] = []
    env: dict[str, str] = {}


class MCPServerToggle(StrictModel):
    enabled: bool