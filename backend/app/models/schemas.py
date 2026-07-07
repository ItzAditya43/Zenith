from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    attachment_ids: list[str] = []  # ids returned by /api/upload


class ConversationCreate(BaseModel):
    title: str = "New chat"


class ConversationRename(BaseModel):
    title: str


class ConfigPatch(BaseModel):
    ollama_host: str | None = None
    model_overrides: dict[str, str | None] | None = None
    capability_keywords: dict[str, list[str]] | None = None
    whisper_model_size: str | None = None
    tts_engine: str | None = None
    piper_voice: str | None = None
