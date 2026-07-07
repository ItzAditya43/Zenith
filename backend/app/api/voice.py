from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services import tts_service, whisper_service

router = APIRouter(prefix="/api/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str


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
    try:
        wav_path = tts_service.synthesize(body.text)
    except Exception as exc:
        raise HTTPException(500, f"Speech synthesis failed: {exc}")
    return FileResponse(wav_path, media_type="audio/wav", filename="speech.wav")
