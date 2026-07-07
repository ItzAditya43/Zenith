# Changelog

## [0.2.0] — 2026-07-08 — Full audit implementation

### Phase 0 — Safety net
- Added `pytest` backend test suite (18 tests): app boot, health endpoint, migration runner, storage CRUD, router logic, chat round-trip, FTS5 search
- Added `schema_version` table + ordered migration runner in `migrations.py`
- Added structured JSONL logging via `structlog` replacing bare `print()` calls
- Routing decisions logged as `{timestamp, message_excerpt, chosen_model, role, reason, latency_ms}`

### Phase 1 — Critical correctness & security
- **Attachment persistence**: moved `_REGISTRY` from in-memory dict to SQLite `attachments` table (migration v2)
- **Attachment validation**: added `python-magic` content-sniffing before dispatching to parsers
- **Attachment cleanup**: background sweeper task (configurable interval) + delete-on-conversation-delete cascade
- **Health check**: `/api/health` now probes Ollama, Whisper, and TTS; returns `ok`/`degraded`/`down` with 503 on `down`
- **Router resilience**: automatic one-time retry against configured fallback model on mid-stream failure; `"downgrade"` SSE event surfaced to client
- **SSE robustness**: `:heartbeat` comment frames every `sse_heartbeat_seconds`; `Request.is_disconnected()` polling
- **Frontend stream resilience**: `AbortController`-based cancellation; interrupted bubbles show retry affordance
- **Auth**: optional shared-secret header/basic-auth middleware (config-gated, off by default); CORS tightened to configurable allowlist
- **Config validation**: `ConfigPatch` Pydantic model rejects invalid enums/ranges with 422

### Phase 2 — Smart routing
- **Embeddings-based semantic routing**: cosine-similarity fallback when embedding model configured
- **Sticky routing**: bias toward previous turn's model when no new hard constraint introduced
- **Context-window-aware routing**: queries `ollama show <model>` (cached), prefers larger-context model when needed
- **Cost/latency-aware routing**: rolling average response time per model tracked
- **Confidence + override UX**: router emits confidence score; `ModelBadge` popover shows it
- **Router unit tests**: `decide()` covered for regex, embedding, sticky, context-window, confidence threshold

### Phase 3 — Voice pipeline
- **Voice discovery UX**: `/api/voice/available_voices` endpoint; Settings UI shows "no voice installed" state
- **Streaming/chunked TTS**: sentence-by-sentence synthesis as assistant reply streams in
- **Barge-in / interrupt**: stop control while `status === "speaking"` halts playback immediately
- **Push-to-talk**: hold-to-talk (`onMouseDown`/`onMouseUp`) + spacebar hold when composer focused; click-toggle as fallback
- **Piper path caching**: `_piper_voice_paths()` cached; invalidated on voice list refresh

### Phase 4 — Multimodal depth
- **OCR fallback**: detects near-empty `pypdf.extract_text()` output, falls back to vision model or `pytesseract`
- **Scene-aware video sampling**: `ffmpeg` scene-change detection for representative frames
- **Multi-document synthesis**: proportional context budgeting across documents with source labels
- **Architecture note**: attachments/router abstraction verified for future image-gen backend

### Phase 5 — RAG / long-term memory
- **Chunking + embedding on upload**: documents chunked at upload time, embedded via `embedding` capability, stored via `sqlite-vec`
- **Retrieval-augmented turns**: top-k relevant chunks retrieved instead of naive head+tail truncation; graceful fallback if no embedding model
- **Conversation memory**: past conversations indexed for cross-conversation retrieval ("what did I discuss about X")
- **Config surface**: chunk size, overlap, top-k exposed in settings with sane defaults

### Phase 6 — Frontend UX/polish
- **Message editing & regeneration**: versioned messages, "edit and resend", "regenerate response"
- **Copy buttons**: copy-code and copy-message in `MessageBubble`
- **Streaming abort**: visible stop button during generation wired to `AbortController`
- **Conversation title auto-generation**: one-shot prompt against fastest model after first assistant response
- **Conversation search**: SQLite FTS5 full-text search surfaced in `Sidebar` (LIKE fallback)
- **Keyboard shortcuts**: Cmd/Ctrl+K search, Cmd/Ctrl+Enter send, Escape closes settings/search
- **Drag-and-drop attachments**: onto composer area
- **Mobile sidebar**: toggle + overlay/backdrop with close-on-click-outside
- **Composer auto-grow**: replaces fixed `rows={1}` overflow-scroll
- **Theme toggle**: explicit dark/light toggle, defaults to `prefers-color-scheme`
- **Loading states**: fade-in for `AmbientField`; loading skeleton for initial conversation load
- **Reduced motion**: `AmbientField` respects `prefers-reduced-motion`
- **Bundle splitting**: `three.js`, `react-syntax-highlighter`, `react-markdown` in lazy-loaded chunks
- **Router transparency popover**: popover on routing badge showing matched keyword/embedding neighbor
- **System notification**: on completed response when tab is backgrounded (Notification API)
- **Delete confirmation**: brief animation instead of instant removal

### Phase 7 — Operational maturity
- **Docker Compose**: `docker-compose.yml` with Ollama, backend, frontend services + health checks
- **Rate limiting**: per-conversation asyncio lock prevents concurrent Ollama OOM
- **Timeouts**: `OllamaClient.chat_stream` uses configurable `request_timeout_seconds` (default 600s)
- **Model pre-warming**: optional pre-load of general model on startup (config-gated, off by default)
- **Cache headers**: `Cache-Control: public, max-age=15` on `/api/config` and `/api/models`
- **`/api/models/refresh`**: explicit endpoint to bust ModelRegistry TTL cache
- **`pyproject.toml`**: moved from hard-pinned `requirements.txt` to PEP 621 with `pip-compile`-compatible deps
- **CI**: GitHub Actions workflow running backend `pytest` + frontend `npm run build` on every push/PR
- **API docs**: FastAPI tags/descriptions/examples on all route handlers
- **Full test coverage**: `router.py`, `orchestrator.py`, `document_service.py`, attachment lifecycle, RAG retrieval path