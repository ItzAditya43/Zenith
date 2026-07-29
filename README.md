# Cortex

A self-hosted, multimodal AI workspace built on your own Ollama instance —
chat, agents, deep research, memory, and voice, all running on your own
hardware. No cloud calls except to your own local Ollama (and the open web,
only when you explicitly ask it to search or attach a link).

Everything in this document reflects what's actually implemented and has
been verified against a real running deployment — not a roadmap, not
aspirational copy.

---

## Table of contents

- [Philosophy](#philosophy)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Feature tour](#feature-tour)
  - [Core chat & multimodal](#core-chat--multimodal)
  - [Model routing](#model-routing)
  - [Memory & personalization](#memory--personalization)
  - [Web & knowledge](#web--knowledge)
  - [Agentic tool use](#agentic-tool-use)
  - [Deep Research](#deep-research)
  - [MCP client support](#mcp-client-support)
  - [Council of models](#council-of-models)
  - [Conversation branching](#conversation-branching)
  - [Document editing](#document-editing)
  - [Folder watcher](#folder-watcher)
  - [Scheduled/recurring turns](#scheduledrecurring-turns)
  - [Data export](#data-export)
  - [Interface](#interface)
- [Configuration reference](#configuration-reference)
- [Safety model](#safety-model)
- [Known limitations](#known-limitations)
- [Extending it](#extending-it)
- [Development](#development)

---

## Philosophy

Cortex's whole pitch is **your own compute, your own models, your own
data** — a self-hosted alternative to the cloud AI assistants, built to be
practically as capable as they are rather than a toy demo. Concretely that
means:

- Nothing leaves your machine except (a) calls to your own Ollama instance
  and (b) calls to the open web, and only when a feature that needs the
  web is explicitly turned on for that message.
- No hosted/paid APIs anywhere in the stack — web search, page reading,
  YouTube transcripts, and MCP tool servers are all free-by-construction
  (keyless endpoints or local subprocesses), not vendor integrations with
  a bill attached.
- Single-user by design. SQLite + a local attachment registry assume one
  person, one machine. Don't put this on the open internet without adding
  auth in front of it (a shared-secret option exists — see
  [Configuration reference](#configuration-reference)).
- Nothing hardcoded to specific model names. The router classifies
  whatever you've `ollama pull`ed by name-matching keywords you can edit
  yourself, so new models work without a code change.

## Architecture

```
cortex/
├── backend/     FastAPI (Python) — Ollama client, router, RAG, agent loop,
│                MCP client, STT/TTS, doc/video parsing, SQLite
└── frontend/    React + Vite — chat UI, command palette, settings
```

Ollama itself is untouched — Cortex talks to it over its normal HTTP API
(`http://localhost:11434` by default, `host.docker.internal:11434` from
inside the Docker deployment). Whisper and Piper TTS run as separate local
processes because Ollama doesn't serve those model types.

### Backend module map

| Module | Responsibility |
|---|---|
| `app/main.py` | FastAPI app, lifespan (background tasks: orphan sweeper, folder scanner, schedule runner, model prewarm), CORS, optional shared-secret auth |
| `app/api/*.py` | One router per feature area — thin, delegates to `services/` |
| `app/services/orchestrator.py` | Ties one plain chat turn together: attachments → context → route → stream → persist |
| `app/services/router.py` | Capability classification (keyword + embedding-based) and model registry |
| `app/services/agent_service.py` | The agentic tool-use loop (bash/files/web/MCP) |
| `app/services/research_service.py` | Deep Research's web-only multi-step loop |
| `app/services/council_service.py` | Concurrent multi-model fan-out |
| `app/services/mcp_service.py` | MCP client (stdio transport) |
| `app/services/memory_service.py` | Long-term fact extraction + injection |
| `app/services/rag_service.py` | Chunking/embedding/retrieval (sqlite-vec) shared by documents, folders, and cross-conversation recall |
| `app/services/folder_service.py` | Watched-folder scanning into RAG |
| `app/services/schedule_service.py` | Recurring unattended turns |
| `app/services/persona_service.py` | Named system-prompt presets |
| `app/services/web_service.py` | DuckDuckGo search + URL/GitHub/Reddit/YouTube reading |
| `app/services/document_service.py` | Text extraction (PDF/DOCX/plain text) + instruction-driven editing |
| `app/services/vision_service.py`, `whisper_service.py`, `tts_service.py` | Image encoding, speech-to-text, text-to-speech |
| `app/db/storage.py` | SQLite persistence, including the branching (parent/active) model |
| `app/db/migrations.py` | Ordered, idempotent schema migrations |

### Frontend module map

| File | Responsibility |
|---|---|
| `App.jsx` | Top-level state, SSE event handling, keyboard shortcuts, toasts |
| `components/Composer.jsx` | Message input, attachments, mic, the mode picker |
| `components/MessageBubble.jsx` | One message: markdown, tool-call cards, branch switcher, citations |
| `components/Sidebar.jsx` | Conversation list, date-grouped, search |
| `components/CommandPalette.jsx` | ⌘K palette |
| `components/SettingsPanel.jsx` | Every configuration surface |
| `components/ToastStack.jsx` | Background-event notifications |
| `lib/api.js` | All backend calls, including the shared SSE-stream parser |

## Quick start

**Prerequisites:**
1. [Ollama](https://ollama.com) running locally with at least one model
   pulled (`ollama pull llama3.2`).
2. `ffmpeg` on your PATH (video frame/audio extraction).
3. Docker + Docker Compose (recommended), or Python 3.11+ and Node 18+ for
   a manual run.

**Docker (recommended):**

```bash
docker compose up -d --build
```

Open `http://localhost:5173`. The backend listens on `:8420` and reaches
your host's Ollama via `host.docker.internal:11434` — see the note at the
top of `docker-compose.yml` if you'd rather run Ollama in its own
container instead. If Ollama shows unreachable from the container, check
that it's bound to more than `127.0.0.1` (`OLLAMA_HOST=0.0.0.0:11434
ollama serve`) — a common gotcha, not a Cortex bug.

**Manual:**

```bash
# Backend
cd backend
./run.sh   # creates a venv, installs requirements, starts uvicorn on :8420

# Frontend (separate terminal)
cd frontend
npm install
cp .env.example .env
npm run dev
```

A Piper voice is optional — download a `.onnx` + `.onnx.json` pair from
the [Piper voices list](https://github.com/rhasspy/piper/blob/master/VOICES.md)
into `backend/data/piper_voices/`. Without one, spoken replies fall back
automatically to your OS's built-in TTS.

### A note on agent mode and your filesystem

Agent mode's `bash`/`read_file`/`write_file`/`edit_file` tools operate on
whatever filesystem the **backend process** can see. In the Docker
deployment that's the container's own throwaway filesystem by default —
the agent can do anything it wants and never touch a real file of yours.
If you want it to work on an actual project, uncomment one of the volume
mounts in `docker-compose.yml` (a single scoped workspace folder, or your
whole home directory) — this is commented out on purpose, not an
oversight, because a local model driving a shell against your real files
is a real decision, not a formality.

## Feature tour

### Core chat & multimodal

- **Streaming text chat** from any installed Ollama model.
- **Images** — attach a photo/screenshot; routed to your vision model
  (llava, qwen2-vl, whatever you've pulled).
- **Documents** — PDF/DOCX/TXT/MD/CSV/JSON get text-extracted; long
  documents are retrieved by relevant chunk (via the RAG index) instead of
  crudely truncated.
- **Video** — sampled frames go to the vision model, the audio track is
  transcribed by Whisper, and both are handed to the model together.
- **Voice in** — hold the mic, Whisper transcribes into the composer.
- **Voice out** — optional spoken replies via Piper (offline neural TTS)
  or a system-voice fallback.
- **Full-text conversation search** (SQLite FTS5, with a LIKE-scan
  fallback on builds without FTS5).
- **Auto-titling** — a small/fast model names new conversations after the
  first exchange.

### Model routing

`app/services/router.py`, config keys `capability_keywords` /
`model_overrides`. No dropdown to manage: the router reads `ollama list`,
tags each installed model by name (vision / code / reasoning / quick /
general / embedding) using keyword lists you can edit from
**Settings → Model routing**, and picks the right one per turn based on
what's attached and what the message looks like. Every reply shows a
badge with the model used and why.

- If an image/video is attached → the **vision** bucket, or a polite
  fallback to general if you have no vision model.
- Code-shaped messages ("write a function", a stack trace) → **code**.
- "step by step", "prove", "solve" → **reasoning**.
- A one-word greeting → **small_fast** (routes to a small model so
  trivial replies don't wait on your biggest one).
- **Sticky routing**: the next turn in a conversation prefers the model
  that answered the last one, so a back-and-forth doesn't bounce between
  models unnecessarily.
- **Embedding-based routing** (`app/services/embedding_router.py`) is
  available as a smarter alternative to keyword matching: embeds a set of
  example prompts per role once, embeds the incoming message, and picks
  the role by cosine similarity. Falls back to the regex router if no
  embedding model is configured.
- **Fallback on mid-stream failure**: if the chosen model dies partway
  through a reply, Cortex retries once against your configured fallback
  model/role and tells you it downgraded.
- Add a keyword to `capability_keywords` (Settings, or directly in
  `data/config.json`) and any model containing it in its name gets
  auto-tagged — nothing is hardcoded to specific model names.

### Memory & personalization

- **Long-term memory** (`memory_service.py`) — after each turn, a small
  model extracts durable personal facts ("uses fish shell", "lives in
  Berlin", "allergic to peanuts") from what you said and stores them,
  deduped. Enabled memories are injected into every future turn's system
  prompt, regardless of which model answers. You get a toast
  ("✓ Remembered: ...") when something new is saved, and full manual
  control (view/add/disable/delete/clear-all) in
  **Settings → Memory & persona**.
- **Cross-conversation recall** — past messages are indexed the same way
  documents are; the orchestrator pulls relevant excerpts from *other*
  conversations into context automatically (excluding the current one),
  so Cortex remembers things you told it in a different chat.
- **Personas** (`persona_service.py`) — named, switchable system-prompt
  presets ("Coding buddy", "Blunt editor"). Pick one per conversation from
  a header dropdown; it overrides the one global system prompt for that
  conversation only. Manage them in **Settings → Personas**.
- **Global system prompt** — a standing instruction sent with every turn
  when no persona is active (Settings → Memory & persona).

### Web & knowledge

- **Web search** (`web_service.py`) — DuckDuckGo's HTML endpoint, no API
  key, no cost. Turn it on from the composer's mode picker.
- **URL reading** — any link pasted into a message is fetched
  automatically, toggle or not. Special-cased for:
  - **GitHub** — a file URL pulls the raw file content; a repo URL pulls
    the README via the REST API.
  - **Reddit** — the read-only `.json` API for clean post/comment text
    (falls back to generic HTML extraction if that's blocked by your
    network).
  - **YouTube** — pulls the actual transcript/captions
    (`youtube-transcript-api`, keyless) plus the title via oEmbed. Reads
    what's *said*, not what's shown — a silent video won't be described.
- Sources used in a turn show up as clickable citation chips under the
  reply.

### Agentic tool use

`agent_service.py`. Off by default (**Settings → Agent tools**, master
switch). When on, the composer's mode picker gets an **Agent** option,
and the model can take multi-step actions instead of answering from
context alone:

**Tools:** `bash`, `read_file`, `write_file`, `edit_file`, `list_dir`,
`web_search`, `fetch_url`, plus anything advertised by configured MCP
servers (see below).

- **`edit_file`** is a precise find-and-replace: give it `old_string` +
  `new_string`, it replaces the one exact occurrence — same safety
  contract as Claude Code's own Edit tool. Fails loudly (not found /
  found N times) instead of guessing which spot was meant. `write_file`
  is for new files or full rewrites; the model is instructed to prefer
  `edit_file` for changing part of an existing file.
- **Autonomy has three modes** (Settings → Agent tools → Autonomy):
  - **Manual** — every tool call pauses for your approval in the chat UI.
  - **Semi-auto** — read-only calls (read/list/search/most bash) run
    immediately; anything that writes or executes ambiguously still asks.
  - **Full-auto** — nothing pauses. Fast, and only as safe as your
    prompts.
- **Every tool call is audited** in a `tool_calls` table regardless of
  mode — nothing the agent does is invisible.
- **Per-conversation working directory** — bind a conversation to a real
  project folder (📁 button in the header, only shown when agent mode is
  on) and the agent's `bash` cwd defaults to it, with relative paths in
  every file tool resolving against it automatically — the same "never
  repeat the full path" convenience Claude Code gets from binding to a
  repo.
- **No filesystem sandbox**, by explicit choice — tools operate on
  whatever the backend process can see (see the Docker note above). This
  is a deliberate "it's your machine" posture, not an oversight.
- **JSON-in-text tool calling**, not Ollama's native `tools` API — native
  function calling only works on a subset of models; prompting for a
  strict JSON object works with any chat model. The cost: small models
  (roughly under ~4B parameters) often skip the protocol entirely and
  answer from guesswork instead of actually calling a tool. This is a
  real limitation of small local models, not a Cortex bug — pin the
  relevant role to a bigger model in Model routing for agent turns to
  work reliably. Verified directly: `qwen2.5-coder:3b` described its plan
  in prose instead of calling a tool; the same request against an 8B
  model correctly called `read_file` then `edit_file` and fixed a real
  bug in a real file.
- **Iteration cap**: 40 tool-call rounds by default before the model is
  forced to give a final answer (configurable, up to 200) — enough for a
  real multi-file task, still bounded so a confused model can't loop
  forever.

### Deep Research

`research_service.py`. A dedicated **Research** mode in the composer:
instead of one search-and-answer, the model plans sub-questions, searches
and fetches multiple sources, and writes a structured cited report.

- Hard-restricted to `web_search`/`fetch_url` only — it never touches
  bash or the filesystem, regardless of whether agent mode is enabled, so
  it needs no approval gate and just runs.
- **Refuses to report before it's actually searched** — this guardrail
  exists because of a real failure caught while building it: a model
  skipped searching entirely and fabricated an entire report with
  invented citations and wrong facts. Deep Research now rejects a
  `{"final": ...}` response until at least one tool call has actually
  executed, feeding the model a correction instead of accepting an
  ungrounded answer.

### MCP client support

`mcp_service.py`. Connect external [Model Context Protocol](https://modelcontextprotocol.io)
tool servers — email, calendar, Notion, whatever's published — instead of
Cortex hand-building each integration. Configure a server (command + args
+ env) in **Settings → Agent tools → MCP servers**; its tools appear in
the agent loop automatically, prefixed `mcp__servername__toolname` so
they can't collide with the built-in set.

- Runs as a local subprocess over stdio — no hosted/paid MCP service
  involved, same free-by-construction posture as everything else.
- Stateless-per-call: a fresh subprocess is spawned, used, and torn down
  for each tool call, so a backend restart never leaves an orphaned MCP
  server process running.
- Unknown external tool behavior is always classified **risky** — same
  approval gate as `bash`/`write_file`.
- "Test connection" in Settings connects right now and lists what a
  configured server actually offers, as a config sanity check.

### Council of models

`council_service.py`. Ask 2+ installed models the same question at once
instead of routing to one — pick the models in **Settings → Council**,
then toggle **Council** in the composer's mode picker.

- Every model streams concurrently (asyncio fan-out into a shared queue)
  — free, since they're all already on your machine and otherwise idle
  between turns.
- Answers persist as **branch siblings** under the same user message
  (reusing the branching model below), so the existing `‹ 1/N ›` switcher
  on the reply is how you flip between what each model said. First model
  to finish becomes the active one by default.
- One model failing doesn't take the others down — errors are per-model.

### Conversation branching

Editing a message or regenerating a reply creates a real branch instead
of silently overwriting history. Messages carry a `parent_id` and an
`active` flag; the linear view you see is just "follow the active child
at each level," and the full tree is still there underneath.

- **Edit** a past message → the old version and everything after it is
  hidden (not deleted), a new branch starts from the same parent.
- **Regenerate** a reply → a fresh sibling is created under the same user
  message; the original is never lost.
- **Switching branches** doesn't just flip one message — it walks forward
  and restores whatever was last active down that path, so switching
  back to an old branch resumes the whole conversation that happened on
  it, not just one message.
- A `‹ 2/3 ›` switcher appears on any message that has siblings.

### Document editing

`app/api/documents.py`. Click **✎** on a document chip, describe the
change, get back a new attachment with a download link — the original is
untouched.

- Scoped to `.txt`/`.md`/`.csv`/`.json` only, deliberately: PDF/DOCX text
  extraction already discards layout/formatting, so "editing" and writing
  one back out would silently drop everything extraction didn't capture.
  Editing a PDF returns a clear error explaining why, rather than
  producing a mangled file.
- One-shot (not agentic) — sends the full document + your instruction to
  the general-role model, returns the complete edited text.

### Folder watcher

`folder_service.py`. Point Cortex at a real directory (a notes vault, a
repo) in **Settings → Folders** and it periodically re-indexes matching
files (`.md`/`.txt`/`.py`/`.js`/`.ts`/`.json` by default) into RAG recall
— no manual upload per file. This is the single biggest "you can't get
this from a cloud chat tool" feature: your own notes become part of what
Cortex knows without you doing anything after initial setup.

- Recursive scan, skips noise directories (`.git`, `node_modules`,
  `__pycache__`, virtualenvs).
- Tracks each file's mtime — re-scans only re-index changed files; a
  file that's deleted or renamed has its chunks dropped so stale content
  doesn't linger in recall.
- Background re-scan every 10 minutes by default (configurable), plus a
  manual "Scan now" per folder.
- Folder content lives in its own RAG bucket, independent of per-document
  RAG and cross-conversation recall — a third `_build_system_context`
  section, same best-effort-per-section pattern (one failing section
  never blocks a turn).

### Scheduled/recurring turns

`schedule_service.py`. "Every morning, research X and summarize" without
touching the keyboard (**Settings → Schedules**).

- A lightweight interval scheduler (minutes, not cron syntax) — enough
  for a personal tool, no parser needed.
- Each schedule gets **one persistent conversation**, created on first
  run and reused after, so a running log builds up instead of a fresh
  orphaned conversation every time.
- Restricted to **chat** and **research** modes — never **agent**. An
  unattended cron job running shell commands with nobody there to
  approve or deny is a real escalation beyond what the approval gates are
  designed for; a scheduled turn that needs to take action should write a
  report for you to review, not act unsupervised.
- Manual "Run now" + expandable run history (status, summary/error) per
  schedule.

### Data export

**Settings → Data**. Everything Cortex knows about you, in a format you
can actually read and keep:

- **JSON** — complete machine-readable dump (every conversation with full
  message history, memories, personas).
- **Markdown** — one readable `.md` file per conversation, zipped, plus
  `memories.md` and `personas.md`. Good for archiving or reading outside
  Cortex entirely.

Both are plain stdlib (`json`/`zipfile`) — no new dependencies, runs
entirely against your own backend.

### Interface

- **Command palette (⌘K)** — jump to any conversation, switch persona,
  run an action (new chat/theme/density/focus), or open a specific
  Settings section directly. Built fresh from current state each time it
  opens.
- **Toast notifications** — low-key corner notifications for background
  events that used to be invisible: auto-titling, memory saves, upload
  failures.
- **Scroll-to-bottom button** — appears when you've scrolled up mid-reply;
  auto-scroll is suppressed while you're reading something above so a
  long streaming answer doesn't yank the view back down.
- **Thinking indicator** — animated dots in the model's signal color
  during the pre-first-token gap, handing off to a blinking cursor once
  real tokens start.
- **Message density** (comfortable/compact) — tighter spacing and smaller
  type for fitting more on screen, persisted like the theme choice.
- **Focus mode** (⌘. or the header's ◎ button) — hides the sidebar and
  all header chrome except the title, centers a narrower reading column.
- **Date-grouped sidebar** (Today / Previous 7 days / Previous 30 days /
  Older) instead of one flat list.
- Calm, static background (no animated particle field), real visual
  definition on assistant replies (a signal-colored left edge matching
  the routed model's capability color), softened text contrast for
  sustained reading.

## Configuration reference

Everything is overridable via environment variables at first boot or
live-editable from the Settings UI (persisted to `data/config.json`).
Grouped by area; see `app/core/config.py` for the authoritative list and
`app/models/schemas.py` for validation ranges.

| Area | Key(s) | Default | What it does |
|---|---|---|---|
| Ollama | `ollama_host` | `http://localhost:11434` | Where Ollama lives |
| Routing | `capability_keywords`, `model_overrides` | see above | How models get tagged/pinned |
| Routing | `fallback_model` | `general` | Role/model used on mid-stream failure |
| Routing | `router_confidence_threshold` | `0.55` | Embedding-router acceptance threshold |
| STT | `whisper_model_size`, `whisper_device`, `whisper_compute_type` | `small`, `cpu`, `int8` | faster-whisper config |
| TTS | `tts_engine`, `piper_voice` | `piper`, `en_US-lessac-medium` | Voice engine + voice |
| Memory | `memory_enabled`, `memory_max_items` | `True`, `200` | Long-term fact extraction |
| Memory | `system_prompt` | `""` | Global persona/standing instructions |
| Memory | `recall_enabled`, `recall_top_k` | `True`, `3` | Cross-conversation recall |
| RAG | `rag_enabled`, `rag_chunk_chars`, `rag_chunk_overlap`, `rag_top_k` | `True`, `1200`, `200`, `5` | Document/folder chunking + retrieval |
| Web | `web_search_max_results`, `web_fetch_max_chars`, `web_fetch_timeout_seconds`, `web_fetch_max_urls_per_turn` | `5`, `4000`, `8`, `3` | Search/fetch limits |
| Agent | `agent_enabled` | `False` | Master switch |
| Agent | `agent_mode` | `manual` | `manual` \| `semi` \| `full` |
| Agent | `agent_max_iterations` | `40` | Tool-call cap per turn (1–200) |
| Agent | `agent_command_timeout_seconds`, `agent_output_max_chars`, `agent_approval_timeout_seconds` | `60`, `4000`, `600` | Bash timeout, result truncation, approval-wait timeout |
| Research | `research_max_iterations` | `10` | Deep Research's step cap |
| Council | `council_models` | `[]` | Which installed models participate |
| Folders | `folder_scan_interval_seconds`, `folder_recall_enabled`, `folder_recall_top_k` | `600`, `True`, `3` | Background re-scan cadence + recall |
| Schedules | `schedule_check_interval_seconds` | `60` | How often due schedules are checked |
| Attachments | `upload_max_bytes`, `upload_orphan_ttl_seconds`, `attachment_ttl_hours` | `200MB`, `24h`, `72h` | Upload limits + cleanup |
| Auth | `auth_enabled`, `auth_shared_secret` | `False`, `""` | Shared-secret auth in front of the API |
| CORS | `cors_allow_origins` | localhost only | Tighten if exposing beyond localhost |
| Ops | `log_level`, `request_timeout_seconds`, `prewarm_model_on_startup` | `INFO`, `600`, `False` | Structured logging, Ollama timeout, cold-start preload |

## Safety model

Cortex is a **personal, single-user tool** — the safety model reflects
that, not a multi-tenant SaaS product:

- **Agent mode is off by default.** You opt in explicitly, and pick an
  autonomy level (manual/semi/full) that matches how much you trust it.
- **No filesystem sandbox** for agent tools, by design — see the Docker
  section above. The tradeoff is explicit: you get real practical power
  (editing your real code, running your real commands) in exchange for
  taking the guardrails off. Start with a scoped workspace mount if
  you're not sure.
- **Scheduled turns can never use agent mode** — unattended + unsupervised
  + shell access is a combination this project deliberately refuses.
- **MCP tools are always risky-classified** — you don't know what an
  external server's tool actually does, so it always gets the same
  approval gate as `write_file`, regardless of your agent mode setting.
- **Full audit trail** — every tool call (built-in or MCP) is logged with
  its args, risk classification, approval status, and result, regardless
  of autonomy mode.
- **Shared-secret auth** (`auth_enabled`) is available if you need to put
  this behind something other than `localhost`, but there's no
  multi-user/permission model — it's one shared secret for the whole API.

## Known limitations

- **Small models frequently fail to follow the tool-calling protocol.**
  This shows up in agent mode, Deep Research, memory extraction, and
  Council — a model under roughly 4B parameters will often describe what
  it *would* do in prose, or emit malformed JSON, instead of actually
  calling a tool. This is a real characteristic of small models, not a
  bug: pin the relevant capability role to a bigger installed model in
  Settings → Model routing for these features to work reliably.
- **YouTube reading is captions-only** — it reads what's said, not what's
  shown. A silent video or one with disabled captions won't be usefully
  read (Deep Research/agent mode get a title-only fallback in that case).
- **Agent mode has no filesystem sandbox** — see [Safety model](#safety-model).
- **Reddit's JSON API can be IP-blocked** by some hosting providers
  (observed from at least one cloud sandbox during development); falls
  back to generic HTML extraction automatically when that happens.
- **DuckDuckGo's HTML search endpoint isn't an official API** — if they
  redesign the page, `web_service.py`'s CSS selectors will need a patch.
  A self-hosted SearXNG instance is a clean drop-in upgrade if this ever
  matters to you (only `search()` would need to change).
- **Single-user by design** — see [Philosophy](#philosophy).

## Extending it

- **New capability bucket** (e.g. "embeddings" for a future feature): add
  keywords to `capability_keywords` and a case in `ModelRouter.decide`.
- **New input type**: add a branch in
  `services/orchestrator.py::build_turn_context` and a `kind` in
  `services/attachments.py::classify`.
- **New built-in agent tool**: add it to `TOOLS` in `agent_service.py`,
  give it a `classify_risk` case, and a dispatch entry in `_execute_tool`.
- **New MCP server**: just configure it in Settings — no code change
  needed, tools are discovered at runtime.
- **Swap SQLite for Postgres**: only `app/db/storage.py` needs to change
  — every route calls through it, nothing else touches SQL directly.
- **Swap the vector store**: `rag_service.py` is the only file that knows
  about `sqlite-vec`; it already falls back to lexical search when the
  extension isn't available, so a different backend just needs the same
  `index_document`/`retrieve` contract.

## Development

```bash
cd backend
source .venv/bin/activate
pytest tests -q          # 18 tests, one requires Ollama reachable
```

```bash
cd frontend
npm run build             # production build + bundle-size check
```

The test suite covers storage/branching, the router, search, and a full
chat round-trip against a real (or mocked) Ollama. One test
(`test_app_boots_and_health`) requires Ollama to actually be reachable —
it's not a flake if it fails with Ollama stopped, that's the expected
contract of the health endpoint.
