"""Text-to-speech. Two engines supported:

- "piper" (default): fast, fully offline, good-quality neural voices via
  the `piper-tts` package + downloaded .onnx voice files. Requires the user
  to grab a voice once (see README) into `piper_voices_dir`.
- "pyttsx3": zero-setup OS-native fallback (lower quality, but works with
  nothing extra installed) — used automatically if no Piper voice is found.

Both paths write a WAV file and return its path; the API layer streams it
back to the browser.
"""
from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from app.core.config import settings


def _piper_voice_paths() -> tuple[Path, Path] | None:
    voices_dir = Path(settings.get("piper_voices_dir"))
    voice = settings.get("piper_voice")
    onnx = voices_dir / f"{voice}.onnx"
    json_cfg = voices_dir / f"{voice}.onnx.json"
    if onnx.exists() and json_cfg.exists():
        return onnx, json_cfg
    return None


def synthesize(text: str) -> Path:
    engine = settings.get("tts_engine", "piper")
    out_path = Path(tempfile.mkstemp(suffix=".wav")[1])

    if engine == "piper":
        voice_paths = _piper_voice_paths()
        if voice_paths:
            return _synthesize_piper(text, out_path, *voice_paths)
        # No voice file installed yet — degrade gracefully instead of crashing.

    return _synthesize_pyttsx3(text, out_path)


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
