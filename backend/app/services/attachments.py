"""Tracks uploaded files between `/api/upload` and `/api/chat`. Kept as an
in-memory index (Cortex is a single-user, self-hosted tool run on one
machine) with the actual bytes persisted to disk under `data/uploads/`."""
from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import UPLOAD_DIR
from app.services.document_service import SUPPORTED_EXTS as DOC_EXTS

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}


@dataclass
class Attachment:
    id: str
    filename: str
    path: Path
    kind: str  # "image" | "video" | "document" | "audio" | "other"


_REGISTRY: dict[str, Attachment] = {}


def classify(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in DOC_EXTS:
        return "document"
    if ext in AUDIO_EXTS:
        return "audio"
    return "other"


def save_upload(filename: str, data: bytes) -> Attachment:
    aid = str(uuid.uuid4())
    dest = UPLOAD_DIR / f"{aid}_{filename}"
    dest.write_bytes(data)
    att = Attachment(id=aid, filename=filename, path=dest, kind=classify(filename))
    _REGISTRY[aid] = att
    return att


def get(attachment_id: str) -> Attachment | None:
    return _REGISTRY.get(attachment_id)


def cleanup(attachment_id: str) -> None:
    att = _REGISTRY.pop(attachment_id, None)
    if att and att.path.exists():
        att.path.unlink(missing_ok=True)
