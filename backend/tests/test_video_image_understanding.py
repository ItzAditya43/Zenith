"""Timestamped video frames, time-range sampling from the question,
timestamped transcripts, and OCR for screenshots."""
from __future__ import annotations

import shutil
import subprocess

import pytest

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.mark.parametrize("q,expected", [
    ("what happens at 2:15?", (125.0, 145.0)),
    ("between 0:30 and 1:10 who speaks", (30.0, 70.0)),
    ("from 1:00:00 to 1:00:20", (3600.0, 3620.0)),
    ("summarise the video", None),
])
def test_requested_range(q, expected):
    from app.services.vision_service import requested_range

    assert requested_range(q) == expected


def test_fmt_ts():
    from app.services.vision_service import fmt_ts

    assert (fmt_ts(5), fmt_ts(75), fmt_ts(3725)) == ("0:05", "1:15", "1:02:05")


@pytest.fixture
def video(tmp_path):
    out = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=30:size=160x120:rate=5",
                    "-pix_fmt", "yuv420p", str(out)], check=True, capture_output=True)
    return out


@needs_ffmpeg
def test_frames_are_timed_and_follow_the_question(video):
    from app.services.vision_service import sample_frames_timed

    whole = sample_frames_timed(video, max_frames=6)
    assert len(whole) == 6 and 0 < whole[0][0] < whole[-1][0] < 30
    focused = sample_frames_timed(video, 10, 14, max_frames=6)
    assert focused and all(10 <= t <= 14 for t, _ in focused)


@needs_ffmpeg
async def test_turn_context_cites_timestamps(fake_ollama, video, monkeypatch):
    from app.services import attachments, orchestrator, vision_service, whisper_service

    att = attachments.save_upload("clip.mp4", video.read_bytes(), "video/mp4")
    monkeypatch.setattr(vision_service, "extract_audio", lambda p: p)
    monkeypatch.setattr(whisper_service, "transcribe", lambda p: {"text": "hi there bye", "segments": [
        {"start": 2.0, "end": 4.0, "text": "hi there"}, {"start": 25.0, "end": 27.0, "text": "bye"}]})
    ctx = await orchestrator.build_turn_context([att.id], "what is shown at 0:06?")
    note = next(t for t in ctx.text_parts if t.startswith("[Video 'clip.mp4'"))
    assert "around the part asked about (0:00–0:16)" in note and "say which timestamp" in note
    transcript = next(t for t in ctx.text_parts if "with timestamps" in t)
    assert "[0:02] hi there" in transcript and "bye" not in transcript  # only the asked-about part
    assert ctx.attachment_summaries[0]["processing"].endswith("on this machine")


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
async def test_screenshot_text_is_read(fake_ollama, tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    from app.services import attachments, orchestrator

    img = Image.new("RGB", (900, 200), "white")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
    except OSError:
        font = ImageFont.load_default(size=36)
    ImageDraw.Draw(img).text((20, 70), "Error: connection refused on port 5432", fill="black", font=font)
    path = tmp_path / "shot.png"
    img.save(path)
    att = attachments.save_upload("shot.png", path.read_bytes(), "image/png")
    ctx = await orchestrator.build_turn_context([att.id], "what does this error mean?")
    ocr = next(t for t in ctx.text_parts if "(OCR)" in t)
    assert "connection refused" in ocr.lower() and "5432" in ocr
    assert "text read with OCR" in ctx.attachment_summaries[0]["processing"]
