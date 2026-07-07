"""Speech-to-text via faster-whisper (CTranslate2 backend — fast on CPU,
no Ollama involved since Ollama doesn't serve Whisper models). The model is
loaded lazily and cached across requests so repeated transcriptions don't
reload weights each time.
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import settings

_model = None
_loaded_size = None


def _get_model():
    global _model, _loaded_size
    size = settings.get("whisper_model_size", "small")
    if _model is None or _loaded_size != size:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            size,
            device=settings.get("whisper_device", "cpu"),
            compute_type=settings.get("whisper_compute_type", "int8"),
        )
        _loaded_size = size
    return _model


def transcribe(audio_path: Path) -> dict:
    """Returns {"text": str, "language": str, "segments": [...]}."""
    model = _get_model()
    segments, info = model.transcribe(str(audio_path), beam_size=5, vad_filter=True)
    seg_list = []
    full_text = []
    for seg in segments:
        seg_list.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        full_text.append(seg.text.strip())
    return {
        "text": " ".join(full_text).strip(),
        "language": info.language,
        "segments": seg_list,
    }
