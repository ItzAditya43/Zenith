from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.services import tts_service, whisper_service

router = APIRouter(prefix="/api/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str
    chunked: bool = False  # if true, stream a JSON sequence of base64 wavs


@router.post("/transcribe")
async def transcribe(file: UploadFile):
    data = await file.read()
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    try:
        result = whisper_service.transcribe(tmp_path)
    except Exception as exc:
        raise HTTPException(500, f"Transcription failed: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)

    return result


@router.post("/speak")
async def speak(body: SpeakRequest):
    """One-shot TTS. Returns a single .wav file.

    For long text the user can opt into chunked mode (Tier 3 #2) which
    streams a JSON sequence of per-sentence WAVs so the browser can
    start playing the first sentence immediately."""
    if body.chunked and bool(settings.get("voice_chunk_sentences", True)):
        def gen():
            for chunk in tts_service.synthesize_chunked(body.text):
                yield json.dumps({"type": "wav", "data_b64": chunk.hex() if isinstance(chunk, bytes) else chunk}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
        return StreamingResponse(gen(), media_type="application/x-ndjson")

    try:
        wav_path = tts_service.synthesize(body.text)
    except Exception as exc:
        raise HTTPException(500, f"Speech synthesis failed: {exc}")
    return FileResponse(wav_path, media_type="audio/wav", filename="speech.wav")


@router.get("/voices")
async def voices():
    """List installed Piper voices and the current selection. Used by
    the Settings panel to show a 'no voice installed' state and by
    the voice-selector dropdown."""
    return {
        "voices": tts_service.available_voices(),
        "tts_engine": settings.get("tts_engine"),
        "piper_voice": settings.get("piper_voice"),
        "piper_voices_dir": settings.get("piper_voices_dir"),
    }