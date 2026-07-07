"""Image + video handling. Images are base64-encoded for Ollama's vision
models. Videos are split into a handful of sampled frames (also base64) plus
their audio track, which is handed off separately to the Whisper service —
Ollama itself has no video concept, so "understanding a video" here means
"look at N frames + read the transcript."
"""
from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from app.core.config import settings

MAX_IMAGE_DIM = 1024  # keep payloads reasonable for local models


def encode_image(path: Path) -> str:
    """Downscales large images (helps small local vision models a lot) and
    returns a base64 string ready for Ollama's `images` field."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        if max(img.size) > MAX_IMAGE_DIM:
            img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
        with tempfile.NamedTemporaryFile(suffix=".jpg") as tmp:
            img.save(tmp.name, "JPEG", quality=85)
            return base64.b64encode(Path(tmp.name).read_bytes()).decode()


def extract_audio(video_path: Path) -> Path:
    """Pulls a mono 16k wav track out of a video for Whisper — uses ffmpeg,
    which must be installed on the host (`apt install ffmpeg` / `brew install ffmpeg`)."""
    out_path = video_path.with_suffix(".extracted.wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(out_path),
        ],
        check=True,
        capture_output=True,
    )
    return out_path


def sample_frames(video_path: Path) -> list[str]:
    """Grabs evenly spaced frames from the video and returns them base64-encoded."""
    max_frames = settings.get("video_max_frames", 8)
    interval = settings.get("video_frame_sample_seconds", 4)

    duration = _probe_duration(video_path)
    count = min(max_frames, max(1, int(duration // interval))) if duration else max_frames

    frames: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        pattern = str(Path(tmp) / "frame_%03d.jpg")
        fps = count / duration if duration else 1 / interval
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vf", f"fps={fps:.4f}", "-frames:v", str(count), pattern,
            ],
            check=True,
            capture_output=True,
        )
        for frame_path in sorted(Path(tmp).glob("frame_*.jpg")):
            frames.append(encode_image(frame_path))
    return frames


def _probe_duration(video_path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
            ],
            check=True, capture_output=True, text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0
