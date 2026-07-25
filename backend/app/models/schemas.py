"""Pydantic models for request/response bodies.

Adding `model_config = ConfigDict(extra="forbid")` makes the API strict
about unknown fields (returns 422 instead of silently ignoring them).
Enums + `Field` constraints on numeric ranges give us a 422 instead of
silently accepting garbage values (e.g. `whisper_model_size = "garbage"`).
"""
from __future__ import annotations

from typing import Literal, Optional

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
    edit_of: Optional[str] = None  # branching: id of the user message being replaced
    regenerate_of: Optional[str] = None  # branching: assistant message id to regenerate


class ConversationCreate(StrictModel):
    title: str = "New chat"


class ConversationRename(StrictModel):
    title: str = Field(min_length=1, max_length=200)


WhisperModelSize = Literal["tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3"]
TtsEngine = Literal["piper", "pyttsx3"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class ConfigPatch(StrictModel):
    """All fields are optional; only the ones the caller actually
    sends get applied. Unknown fields are rejected (extra='forbid')."""

    ollama_host: Optional[str] = Field(default=None, min_length=1, max_length=500)
    model_overrides: Optional[dict[str, Optional[str]]] = None
    capability_keywords: Optional[dict[str, list[str]]] = None
    whisper_model_size: Optional[WhisperModelSize] = None
    tts_engine: Optional[TtsEngine] = None
    piper_voice: Optional[str] = Field(default=None, min_length=1, max_length=200)
    fallback_model: Optional[str] = Field(default=None, min_length=1, max_length=200)
    auth_enabled: Optional[bool] = None
    auth_shared_secret: Optional[str] = None
    cors_allow_origins: Optional[list[str]] = None
    rag_enabled: Optional[bool] = None
    rag_chunk_chars: Optional[int] = Field(default=None, ge=200, le=20_000)
    rag_chunk_overlap: Optional[int] = Field(default=None, ge=0, le=5_000)
    rag_top_k: Optional[int] = Field(default=None, ge=1, le=20)
    doc_ocr_fallback: Optional[bool] = None
    video_scene_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    router_confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    log_level: Optional[LogLevel] = None
    request_timeout_seconds: Optional[int] = Field(default=None, ge=5, le=7200)
    prewarm_model_on_startup: Optional[bool] = None
    sse_heartbeat_seconds: Optional[int] = Field(default=None, ge=0, le=120)
    upload_max_bytes: Optional[int] = Field(default=None, ge=1_024, le=5 * 1024 * 1024 * 1024)
    max_context_messages: Optional[int] = Field(default=None, ge=1, le=200)
    attachment_ttl_hours: Optional[int] = Field(default=None, ge=1, le=24 * 30)
    voice_chunk_sentences: Optional[bool] = None
    ui_experimental: Optional[bool] = None
    memory_enabled: Optional[bool] = None
    memory_max_items: Optional[int] = Field(default=None, ge=10, le=2000)
    system_prompt: Optional[str] = Field(default=None, max_length=8000)
    recall_enabled: Optional[bool] = None
    recall_top_k: Optional[int] = Field(default=None, ge=1, le=10)
    web_search_max_results: Optional[int] = Field(default=None, ge=1, le=10)
    web_fetch_max_chars: Optional[int] = Field(default=None, ge=500, le=20_000)
    web_fetch_timeout_seconds: Optional[int] = Field(default=None, ge=2, le=60)
    web_fetch_max_urls_per_turn: Optional[int] = Field(default=None, ge=0, le=10)
    agent_enabled: Optional[bool] = None
    agent_mode: Optional[Literal["manual", "semi", "full"]] = None
    agent_max_iterations: Optional[int] = Field(default=None, ge=1, le=25)
    agent_command_timeout_seconds: Optional[int] = Field(default=None, ge=5, le=600)
    agent_output_max_chars: Optional[int] = Field(default=None, ge=500, le=20_000)
    agent_approval_timeout_seconds: Optional[int] = Field(default=None, ge=30, le=3600)
    research_max_iterations: Optional[int] = Field(default=None, ge=2, le=30)
    council_models: Optional[list[str]] = Field(default=None, max_length=6)


class MemoryCreate(StrictModel):
    content: str = Field(min_length=1, max_length=300)
    category: str = Field(default="fact", max_length=40)


class MemoryToggle(StrictModel):
    enabled: bool


class PersonaCreate(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    system_prompt: str = Field(min_length=1, max_length=8000)
    icon: Optional[str] = Field(default=None, max_length=8)


class PersonaUpdate(StrictModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
    system_prompt: Optional[str] = Field(default=None, min_length=1, max_length=8000)
    icon: Optional[str] = Field(default=None, max_length=8)


class ConversationPersonaSet(StrictModel):
    persona_id: Optional[str] = None


class CouncilRequest(StrictModel):
    conversation_id: str
    message: str
    attachment_ids: list[str] = []
    models: list[str] = Field(min_length=1, max_length=6)