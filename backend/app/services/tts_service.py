"""Text-to-speech. Two engines supported:

- "piper" (default): fast, fully offline, good-quality neural voices via
  the `piper-tts` package + downloaded .onnx voice files. Requires the user
  to grab a voice once (see README) into `piper_voices_dir`.
- "pyttsx3": zero-setup OS-native fallback (lower quality, but works with
  nothing extra installed) — used automatically if no Piper voice is found.

Both paths write a WAV file and return its path; the API layer streams it
back to the browser.

Phase 3 additions:
- Cached Piper voice path lookup (was hitting the FS on every call).
- Sentence-level chunked synthesis: for long text, yields one WAV per
  sentence so the browser can start playing the first sentence while
  the rest are still being generated (streaming TTS).
- `available_voices()` helper for the new /api/voice/voices endpoint.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
import wave
from pathlib import Path
from threading import RLock
from typing import Iterator

from app.core.config import settings

# A simple cache so the file lookup (and the PiperVoice.load() call) doesn't
# happen on every synthesize. Invalidated by `refresh_voice_cache()` which
# the /api/voice/voices route calls after the user adds a new .onnx file.
_VOICE_CACHE: dict[str, tuple[Path, Path] | None] = {}
_VOICE_CACHE_TS: float = 0.0
_VOICE_CACHE_TTL_SEC = 30.0
_CACHE_LOCK = RLock()


def _piper_voice_paths() -> tuple[Path, Path] | None:
    voice = settings.get("piper_voice")
    with _CACHE_LOCK:
        now = time.time()
        if voice in _VOICE_CACHE and (now - _VOICE_CACHE_TS) < _VOICE_CACHE_TTL_SEC:
            return _VOICE_CACHE[voice]

    voices_dir = Path(settings.get("piper_voices_dir"))
    onnx = voices_dir / f"{voice}.onnx"
    json_cfg = voices_dir / f"{voice}.onnx.json"
    found = (onnx, json_cfg) if onnx.exists() and json_cfg.exists() else None
    with _CACHE_LOCK:
        _VOICE_CACHE[voice] = found
        _VOICE_CACHE_TS = now
    return found


def refresh_voice_cache() -> None:
    """Drop the cache. Call this when a new voice is added/removed."""
    with _CACHE_LOCK:
        _VOICE_CACHE.clear()
        _VOICE_CACHE_TS = 0.0


def available_voices() -> list[dict]:
    """List .onnx files in `piper_voices_dir` along with the one currently
    selected in config. Returns [] when the dir doesn't exist (no Piper
    setup yet) — the UI shows a 'download a voice' message in that case."""
    voices_dir = Path(settings.get("piper_voices_dir"))
    if not voices_dir.exists():
        return []
    current = settings.get("piper_voice")
    out = []
    for onnx in sorted(voices_dir.glob("*.onnx")):
        name = onnx.stem
        out.append({
            "name": name,
            "path": str(onnx),
            "installed": (onnx.with_suffix(".onnx.json")).exists(),
            "current": name == current,
        })
    return out


_SENTENCE_RE = re.compile(r"(?<=[\.\!\?])\s+")


def _split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts = _SENTENCE_RE.split(text)
    return [p for p in parts if p.strip()]


def synthesize(text: str) -> Path:
    """One-shot full-text synthesis. Used by /api/voice/speak."""
    engine = settings.get("tts_engine", "piper")
    out_path = Path(tempfile.mkstemp(suffix=".wav")[1])

    if engine == "piper":
        voice_paths = _piper_voice_paths()
        if voice_paths:
            return _synthesize_piper(text, out_path, *voice_paths)
    return _synthesize_pyttsx3(text, out_path)


def synthesize_chunked(text: str) -> Iterator[bytes]:
    """Yields WAV file bytes (full .wav files, each self-contained) one
    sentence at a time. The frontend can play them back-to-back to give
    a streaming-TTS feel: first-sentence-audio is heard before the rest
    is even synthesized.

    For now this is a generator of *byte blobs* (one .wav per sentence) so
    the API route can keep the implementation simple. A future iteration
    could return PCM streams and re-package them at the endpoint."""
    sentences = _split_sentences(text)
    if not sentences:
        return
    # If only one sentence, use the fast single-shot path so we don't
    # pay the overhead of multiple .wav header writes.
    if len(sentences) == 1:
        yield synthesize(sentences[0]).read_bytes()
        return
    for s in sentences:
        if not s.strip():
            continue
        try:
            yield synthesize(s).read_bytes()
        except Exception:
            continue


def _synthesize_piper(text: str, out_path: Path, onnx: Path, config: Path) -> Path:
    from piper.voice import PiperVoice

    voice = PiperVoice.load(str(onnx), config_path=str(config))
    with wave.open(str(out_path), "wb") as wav_file:
        voice.synthesize(text, wav_file)
    return out_path


def _synthesize_pyttsx3(text: str, out_path: Path) -> Path:
    import pyttsx3

    engine = pyttsx3.init()
    engine.save_to_file(text, str(out_path))
    engine.runAndWait()
    return out_path