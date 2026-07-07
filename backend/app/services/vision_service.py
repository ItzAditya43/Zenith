"""Image + video handling. Images are base64-encoded for Ollama's vision
models. Videos are split into a handful of sampled frames (also base64) plus
their audio track, which is handed off separately to the Whisper service —
Ollama itself has no video concept, so "understanding a video" here means
"look at N frames + read the transcript."

Phase 4 #2: scene-aware frame sampling via ffmpeg's `select=gt(scene,...)`
filter, so the chosen frames correspond to actual scene changes rather
than arbitrary fixed-interval ticks. Falls back to fixed-interval
sampling if the scene filter returns no frames (very short clips, etc.).
"""
from __future__ import annotations

import base64
import os
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
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video_path),
                "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(out_path),
            ],
            check=True, capture_output=True,
        )
    except Exception:
        # Make sure we don't leak a 0-byte file.
        out_path.unlink(missing_ok=True)
        raise
    return out_path


def sample_frames(video_path: Path) -> list[str]:
    """Sample representative frames from the video.

    Phase 4 #2: prefer ffmpeg's scene-change filter so frames are picked
    at visually distinct moments. Threshold is configurable
    (`video_scene_threshold`, 0..1). Falls back to fixed-interval sampling
    when the scene filter returns < 2 frames (very short / static videos)
    so the caller still gets *something* useful."""
    max_frames = settings.get("video_max_frames", 8)
    threshold = float(settings.get("video_scene_threshold", 0.3))

    frames = _sample_scene(video_path, threshold, max_frames)
    if len(frames) < 2:
        # Fallback: even-spaced frames.
        frames = _sample_fixed(video_path, max_frames)
    return frames


def _sample_scene(video_path: Path, threshold: float, max_frames: int) -> list[str]:
    """Use ffmpeg's `select=gt(scene,T)` to grab frames at scene changes."""
    with tempfile.TemporaryDirectory() as tmp:
        pattern = str(Path(tmp) / "scene_%03d.jpg")
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-vf", f"select='gt(scene,{threshold})',showinfo",
                    "-vsync", "vfr", "-frames:v", str(max_frames), pattern,
                ],
                check=True, capture_output=True,
            )
        except Exception:
            return []
        out = []
        for frame_path in sorted(Path(tmp).glob("scene_*.jpg")):
            out.append(encode_image(frame_path))
        return out


def _sample_fixed(video_path: Path, max_frames: int) -> list[str]:
    interval = settings.get("video_frame_sample_seconds", 4)
    duration = _probe_duration(video_path)
    count = min(max_frames, max(1, int(duration // interval))) if duration else max_frames
    frames: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        pattern = str(Path(tmp) / "frame_%03d.jpg")
        fps = count / duration if duration else 1 / interval
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-vf", f"fps={fps:.4f}", "-frames:v", str(count), pattern,
                ],
                check=True, capture_output=True,
            )
        except Exception:
            return []
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