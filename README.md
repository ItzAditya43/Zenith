# Cortex

A self-hosted, multimodal chat client for your own Ollama instance — text, images,
documents, video, and voice in and out — with a router that automatically picks
which installed model handles each turn.

Everything runs on your machine. No cloud calls except to your own Ollama.

---

## What it does

- **Text chat** — streaming replies from any Ollama model you have installed.
- **Images** — attach a photo/screenshot, Cortex sends it to your vision model
  (llava, bakllava, moondream, qwen2-vl, whatever you've pulled).
- **Documents** — PDF / DOCX / TXT / MD / CSV get their text extracted and dropped
  into context (long documents are trimmed to keep the head + tail).
- **Video** — Cortex samples a handful of frames (vision model) *and* extracts +
  transcribes the audio track (Whisper), then hands both to the model together.
- **Voice in** — hold the mic, it records, Whisper transcribes it into the composer.
- **Voice out** — optional "speak replies" toggle, using Piper (offline neural TTS)
  or a system-voice fallback.
- **Automatic model routing** — no dropdown to manage. The router reads
  `ollama list`, tags each installed model by name (vision / code / reasoning /
  quick / general), and picks the right one per turn based on what's attached and
  what the message looks like. Every reply shows a badge with the model it used
  and why. You can pin any role to a specific model from Settings.

## Architecture

```
cortex/
├── backend/     FastAPI (Python) — Ollama client, router, STT/TTS, doc/video parsing, SQLite
└── frontend/    React + Vite + Three.js — chat UI, ambient background, settings
```

Ollama itself is untouched — Cortex talks to it over its normal HTTP API
(`http://localhost:11434` by default). Whisper and TTS run as separate local
processes because Ollama doesn't serve those model types.

## Prerequisites

1. **Ollama** running locally with at least one model pulled:
   ```bash
   ollama pull llama3.2       # general text
   ollama pull llava          # images/video frames — optional but recommended
   ollama pull deepseek-coder # optional, sharper for code
   ```
   Cortex works with whatever you already have; it detects models by name (see
   "Teaching the router about new models" below).

2. **ffmpeg** on your PATH — required for video frame/audio extraction.
   ```bash
   sudo apt install ffmpeg      # Debian/Ubuntu
   brew install ffmpeg          # macOS
   ```

3. **Python 3.10+** and **Node 18+**.

4. **A Piper voice** (optional, only if you want spoken replies). Download any
   voice `.onnx` + `.onnx.json` pair from
   https://github.com/rhasspy/piper/blob/master/VOICES.md into
   `backend/data/piper_voices/`, e.g. `en_US-lessac-medium.onnx` +
   `en_US-lessac-medium.onnx.json`. Without this, voice replies fall back
   automatically to your OS's built-in TTS (lower quality, zero setup).

## Running it

**Backend:**
```bash
cd backend
./run.sh
# or manually:
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8420 --reload
```

**Frontend:**
```bash
cd frontend
npm install
cp .env.example .env      # points the UI at http://localhost:8420
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`).

## How the router decides

`backend/app/services/router.py` + the `capability_keywords` in
`backend/app/core/config.py`:

1. If an image or video is attached → the **vision** bucket is used (if you have
   a vision model; otherwise it politely falls back to general and says so).
2. Otherwise, the message text is scanned for cheap signals:
   - looks like code / an error / "write a script" → **code**
   - "step by step", "prove", "solve", "calculate" → **reasoning**
   - a one-word greeting/thanks → **small_fast** (routes to a small model if
     you have one, so trivial replies don't wait on your biggest model)
   - anything else → **general**
3. Each bucket maps to whichever installed model matches its keyword list, or
   your manual override from Settings, or `general` as a last resort.

### Teaching the router about new models

Nothing is hardcoded to specific model names beyond the keyword lists in
`capability_keywords` (editable via `PATCH /api/config`, or directly in
`backend/data/config.json` once it's created). Add a keyword and any model
containing it in its name gets tagged automatically. Or just open Settings →
Model routing and pin a role to an exact model — overrides always win.

## Known limitations (read before you assume it's broken)

- **Whisper and Piper models are not bundled.** `faster-whisper` downloads its
  chosen size from Hugging Face on first use; make sure the machine running the
  backend has internet access the first time (fully offline after that).
- **No RAG / vector search over documents.** Long documents are truncated
  (head + tail) rather than chunked-and-retrieved — good enough for "summarize
  this," not for "search across 400 pages." That's a natural next step if you
  want it (a `sqlite-vec` or `chroma` index over document chunks, keyed by the
  same attachment id).
- **Video understanding is frame-sampling, not real video comprehension** —
  Ollama has no native video model, so this is "look at N stills + read the
  transcript," which covers most real use (a screen recording, a clip someone
  sends you) but won't catch fast motion between sampled frames.
- **Single-user by design.** SQLite + an in-memory attachment registry assume
  one person, one machine — intentional for a self-hosted tool, but don't put
  this on the open internet without adding auth in front of it.

## Extending it

- New capability bucket (e.g. "embeddings" for a future RAG feature): add
  keywords to `capability_keywords` and a case in `ModelRouter.decide`.
- New input type: add a branch in `services/orchestrator.py::build_turn_context`
  and a `kind` in `services/attachments.py::classify`.
- Swap SQLite for Postgres: only `app/db/storage.py` needs to change — every
  route calls through it, nothing else touches SQL directly.
