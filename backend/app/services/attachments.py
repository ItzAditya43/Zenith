"""Tracks uploaded files between `/api/upload` and `/api/chat`.

Metadata is persisted in SQLite (so lookups survive backend restarts);
the actual bytes live under `data/uploads/`.
"""
from __future__ import annotations

import mimetypes
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.core.config import (
    upload_dir as _upload_dir,
    settings,
)
from app.core.logging import get_logger
from app.services.document_service import SUPPORTED_EXTS as DOC_EXTS

log = get_logger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}


class AttachmentError(ValueError):
    """Raised for invalid/untrusted uploads. Maps to a 4xx at the API layer."""


@dataclass
class Attachment:
    id: str
    filename: str
    path: Path
    mime_type: str
    size: int
    kind: str  # "image" | "video" | "document" | "audio" | "other"
    created_at: float


def classify(filename: str, mime_type: str | None = None) -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in DOC_EXTS:
        return "document"
    if ext in AUDIO_EXTS:
        return "audio"
    # Fall back to MIME hint if extension is unrecognised.
    if mime_type:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("video/"):
            return "video"
        if mime_type.startswith("audio/"):
            return "audio"
    return "other"


def _guess_mime(filename: str, declared: str | None) -> str:
    if declared and declared != "application/octet-stream":
        return declared
    guess, _ = mimetypes.guess_type(filename)
    return guess or "application/octet-stream"


def _sniff_mime(path: Path, fallback: str) -> str:
    """Best-effort magic-byte sniff. Falls back silently if libmagic is missing."""
    try:
        import magic  # type: ignore

        detected = magic.from_file(str(path), mime=True)
        if detected:
            return detected
    except (ImportError, OSError) as exc:
        log.debug("upload.magic_sniff_unavailable", error=str(exc))
    return fallback


@contextmanager
def _conn():
    """One transaction per call: commits (or rolls back) and closes.
    Same WAL/busy_timeout setup as app.db.storage — both modules share
    the one SQLite file."""
    from app.db.storage import _connect

    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def save_upload(
    filename: str,
    data: bytes,
    declared_mime: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
) -> Attachment:
    """Persist a new upload to disk and SQLite. Performs content sniffing
    to catch mismatched extension vs. actual content (defence-in-depth)."""
    if not filename:
        raise AttachmentError("Filename is required.")
    if not data:
        raise AttachmentError("Empty file.")

    cap = int(settings.get("upload_max_bytes", 200 * 1024 * 1024))
    if len(data) > cap:
        raise AttachmentError(f"File too large ({len(data)} bytes; cap {cap}).")

    aid = str(uuid.uuid4())
    upload_dir = _upload_dir()
    dest = upload_dir / f"{aid}_{Path(filename).name}"
    dest.write_bytes(data)

    mime = _guess_mime(filename, declared_mime)
    sniffed = _sniff_mime(dest, mime)
    if (
        sniffed
        and sniffed != "application/octet-stream"
        and sniffed != mime
    ):
        log.warning(
            "upload.mime_mismatch",
            filename=filename,
            declared=mime,
            sniffed=sniffed,
        )
        # Hard-reject obvious mismatches (e.g. .png that's really plain text).
        # We only fail when the declared and sniffed types belong to different
        # *categories* — image vs. text vs. archive — to avoid false positives
        # on text formats (txt/json) where libmagic is unreliable.
        if not _is_compatible_kind(mime, sniffed, filename):
            dest.unlink(missing_ok=True)
            raise AttachmentError(
                f"File content does not match its extension "
                f"(declared={mime}, sniffed={sniffed})."
            )

    kind = classify(filename, sniffed)
    now = time.time()

    with _conn() as conn:
        conn.execute(
            """INSERT INTO attachments
               (id, filename, path, mime_type, size, kind, conversation_id, message_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, filename, str(dest), sniffed, len(data), kind, conversation_id, message_id, now),
        )
    log.info("upload.saved", id=aid, filename=filename, kind=kind, size=len(data))
    return Attachment(
        id=aid, filename=filename, path=dest, mime_type=sniffed,
        size=len(data), kind=kind, created_at=now,
    )


def bind_to_message(attachment_id: str, message_id: str) -> None:
    """Link an existing attachment to a message id (used after the
    assistant turn completes)."""
    with _conn() as conn:
        conn.execute(
            "UPDATE attachments SET message_id = ? WHERE id = ?",
            (message_id, attachment_id),
        )


def _is_compatible_kind(declared: str, sniffed: str, filename: str) -> bool:
    """Heuristic: treat two mime types as compatible if either side is
    generic (octet-stream/text/plain) or they share a top-level category.
    Used to flag genuine mismatches without false-positiving on text files."""
    if not declared or not sniffed:
        return True
    if declared == "application/octet-stream" or sniffed == "application/octet-stream":
        return True
    if declared.startswith("text/") or sniffed.startswith("text/"):
        return True
    decl_top = declared.split("/")[0]
    sniff_top = sniffed.split("/")[0]
    return decl_top == sniff_top


def get(attachment_id: str) -> Attachment | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
    if not row:
        return None
    return Attachment(
        id=row["id"],
        filename=row["filename"],
        path=Path(row["path"]),
        mime_type=row["mime_type"] or "application/octet-stream",
        size=row["size"],
        kind=row["kind"],
        created_at=row["created_at"],
    )


def list_orphans(older_than_seconds: float) -> list[Attachment]:
    cutoff = time.time() - older_than_seconds
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM attachments
               WHERE conversation_id IS NULL AND created_at < ?""",
            (cutoff,),
        ).fetchall()
    return [
        Attachment(
            id=r["id"], filename=r["filename"], path=Path(r["path"]),
            mime_type=r["mime_type"] or "application/octet-stream",
            size=r["size"], kind=r["kind"], created_at=r["created_at"],
        )
        for r in rows
    ]


def cleanup(attachment_id: str) -> None:
    att = get(attachment_id)
    if not att:
        return
    if att.path.exists():
        att.path.unlink(missing_ok=True)
    # also drop any *.extracted.wav sidecars ffmpeg wrote next to the source
    for sibling in att.path.parent.glob(att.path.name + ".*"):
        if sibling.suffix.lower() in {".wav", ".extracted.wav"} or sibling.name.endswith(".extracted.wav"):
            sibling.unlink(missing_ok=True)
    with _conn() as conn:
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    log.info("upload.cleaned", id=attachment_id)


def cleanup_for_conversation(conversation_id: str) -> int:
    """Removes every upload bound to a conversation (e.g. when that
    conversation is deleted). Returns the number of files removed."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM attachments WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
    removed = 0
    for r in rows:
        try:
            p = Path(r["path"])
            if p.exists():
                p.unlink(missing_ok=True)
            for sibling in p.parent.glob(p.name + ".*"):
                sibling.unlink(missing_ok=True)
            removed += 1
        except Exception as exc:  # never let cleanup abort the caller
            log.warning("upload.cleanup_failed", id=r["id"], error=str(exc))
    with _conn() as conn:
        conn.execute(
            "DELETE FROM attachments WHERE conversation_id = ?", (conversation_id,)
        )
    return removed


def sweep_orphans() -> int:
    """Delete unattached uploads older than the configured TTL. Safe to call
    from a background task or after each upload."""
    ttl = int(settings.get("upload_orphan_ttl_seconds", 24 * 3600))
    orphans = list_orphans(ttl)
    for a in orphans:
        cleanup(a.id)
    if orphans:
        log.info("upload.swept_orphans", count=len(orphans), ttl=ttl)
    return len(orphans)