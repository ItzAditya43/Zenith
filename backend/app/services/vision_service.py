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
import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from app.core.config import settings

MAX_IMAGE_DIM = 1024  # keep payloads reasonable for local models


def encode_image(path: Path) -> str:
    """Downscales large images (helps small local vision models a lot) and
    returns a base64 string ready for Ollama's `images` field."""
    with Image.open(path) as src:
        img = src.convert("RGB")
    if max(img.size) > MAX_IMAGE_DIM:
        img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
    # In memory: re-opening a NamedTemporaryFile by name fails on Windows.
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


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


# ---- timestamps, time ranges, OCR ---------------------------------------------------

def fmt_ts(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def parse_time(text: str) -> float | None:
    parts = text.strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if not 1 <= len(nums) <= 3:
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


_TS = r"(\d{1,2}:\d{2}(?::\d{2})?)"


def requested_range(question: str) -> tuple[float, float] | None:
    """A moment or range the user asked about: "at 2:15", "around 1:02:30",
    "between 0:30 and 1:10", "from 3:00 to 3:20". A single moment becomes a
    ±10 s window."""
    import re

    q = question or ""
    m = re.search(rf"(?:between|from)\s+{_TS}\s+(?:and|to|-|–)\s+{_TS}", q, re.I)
    if m:
        a, b = parse_time(m.group(1)), parse_time(m.group(2))
        if a is not None and b is not None and b > a:
            return a, b
    m = re.search(rf"(?:at|around|near|@)\s*{_TS}", q, re.I) or re.search(rf"\b{_TS}\b", q)
    if m:
        t = parse_time(m.group(1))
        if t is not None:
            return max(0.0, t - 10), t + 10
    return None


def sample_frames_timed(video_path: Path, start: float | None = None, end: float | None = None,
                        max_frames: int | None = None) -> list[tuple[float, str]]:
    """[(seconds, base64 jpeg)] evenly across the whole video, or densely
    inside [start, end] when the user asked about a moment."""
    max_frames = int(max_frames or settings.get("video_max_frames", 8))
    duration = _probe_duration(video_path)
    lo = max(0.0, start or 0.0)
    hi = min(end, duration) if (end is not None and duration) else (end or duration)
    if not hi or hi <= lo:
        return [(0.0, f) for f in sample_frames(video_path)]
    span = hi - lo
    count = max(1, min(max_frames, int(span // 1) or 1))
    times = [lo + span * (i + 0.5) / count for i in range(count)]
    out: list[tuple[float, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            frame = Path(tmp) / f"f{i:03d}.jpg"
            try:
                subprocess.run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video_path), "-frames:v", "1", "-q:v", "3", str(frame)],
                               check=True, capture_output=True, timeout=60)
            except Exception:
                continue
            if frame.exists():
                out.append((t, encode_image(frame)))
    return out


def ocr_image(path: Path, max_chars: int = 3000) -> str:
    """Text in an image (screenshots, photos of documents) via tesseract,
    if installed. "" when there's none or tesseract is missing."""
    import shutil

    if not shutil.which("tesseract"):
        return ""
    try:
        res = subprocess.run(["tesseract", str(path), "stdout", "--psm", "3"], capture_output=True, text=True, timeout=60)
    except Exception:
        return ""
    text = "\n".join(ln.rstrip() for ln in res.stdout.splitlines() if ln.strip())
    # A photo with no real text produces a few stray characters; keep only real text.
    words = [w for w in text.split() if len(w) > 2 and any(c.isalpha() for c in w)]
    return text[:max_chars] if len(words) >= 4 else ""


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