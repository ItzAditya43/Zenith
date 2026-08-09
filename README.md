# Zenith

A self-hosted, multimodal AI workspace built on your own Ollama instance —
chat, a Claude-Code-class coding agent, deep research, memory, image
generation, and voice, all running on your own hardware. No cloud calls
except to your own local Ollama (and the open web, only when you explicitly
ask it to search or attach a link).

Run it as a Docker stack, install it as a **native desktop app** (Tauri +
frozen backend), or reach it from your phone over your LAN/Tailscale — same
local backend, same data.

Everything in this document reflects what's actually implemented and has
been verified against a real running deployment — not a roadmap, not
aspirational copy.

This README is written for developers. If you're pointing someone
non-technical at this project, [`docs/index.html`](docs/index.html) is a
short, plain-language page explaining what it is and why — open it directly,
or enable it for free via GitHub Pages (Settings → Pages → deploy from
`/docs` on this branch).

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
  - [Code editor panel](#code-editor-panel)
  - [Document editing](#document-editing)
  - [Image generation](#image-generation)
  - [Model management](#model-management)
  - [Unified search](#unified-search)
  - [Import from ChatGPT / Claude](#import-from-chatgpt--claude)
  - [Folder watcher](#folder-watcher)
  - [Scheduled/recurring turns](#scheduledrecurring-turns)
  - [Data export](#data-export)
  - [Passcode lock](#passcode-lock)
  - [Knowledge graph](#knowledge-graph)
  - [Self-improving memory](#self-improving-memory)
  - [Ambient daily digest](#ambient-daily-digest)
  - [Automation rules + outbound webhooks](#automation-rules--outbound-webhooks)
  - [Task board](#task-board)
  - [Interface](#interface)
- [Desktop app](#desktop-app)
- [Browser extension](#browser-extension)
- [Mobile & multi-device](#mobile--multi-device)
- [Configuration reference](#configuration-reference)
- [Safety model](#safety-model)
- [Known limitations](#known-limitations)
- [Extending it](#extending-it)
- [Development](#development)
  - [Continuous integration](#continuous-integration)
- [License](#license)

---

## Philosophy

Zenith's whole pitch is **your own compute, your own models, your own
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
zenith/
├── backend/     FastAPI (Python) — Ollama client, router, RAG, agent loop,
│                MCP client, browser automation, image gen, STT/TTS, SQLite
├── frontend/    React + Vite — chat UI, command palette, settings, PWA
├── desktop/     Tauri v2 shell — packages the above into a native app
│                (see DESKTOP.md); the frozen backend runs as a sidecar;
│                system tray + global hotkey live in src-tauri/src/main.rs
└── extension/   Manifest V3 browser extension (load unpacked) — sends a
                 page or selection into a new Zenith conversation
```

Ollama itself is untouched — Zenith talks to it over its normal HTTP API
(`http://localhost:11434` by default, `host.docker.internal:11434` from
inside the Docker deployment). Whisper and Piper TTS run as separate local
processes because Ollama doesn't serve those model types.

### Backend module map

| Module | Responsibility |
|---|---|
| `app/main.py` | FastAPI app, lifespan (background tasks: orphan sweeper, folder scanner, schedule runner, model prewarm), CORS (+ opt-in LAN/Tailscale), shared-secret auth, passcode-lock middleware |
| `app/api/*.py` | One router per feature area — thin, delegates to `services/` (incl. `lock.py`, `images.py`) |
| `app/services/orchestrator.py` | Ties one plain chat turn together: attachments → context → route → stream → persist |
| `app/services/router.py` | Capability classification (keyword + embedding-based) and model registry |
| `app/services/agent_service.py` | The agentic tool-use loop — bash, files (with diff-preview + undo), persistent shell sessions, browser automation, first-class git, run_checks, sub-agent delegation, MCP; plan-first mode; checkpoint/resume |
| `app/services/browser_service.py` | Headless-Chromium browser automation over raw CDP (navigate/click/type/read) |
| `app/services/image_service.py` | Local Stable Diffusion (AUTOMATIC1111-compatible) image generation |
| `app/services/import_service.py` | Ingest ChatGPT/Claude conversation exports |
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
| `app/services/stream_registry.py` | Decouples chat generation from the HTTP connection that started it — buffered, replayable, multi-subscriber, so a dropped connection can reconnect instead of losing the reply |
| `app/services/events.py` | Internal event bus (`digest_generated`, `schedule_completed`, `urgent_email`, `memory_conflict_found`, `folder_file_added`) fanning out to webhooks and automation rules |
| `app/services/webhook_service.py` | Fire-and-forget outbound POST to configured URLs on a real event |
| `app/services/automation_service.py` | User-defined trigger → action rules on the same event bus (prompt into a persistent conversation, or a one-off webhook) |
| `app/services/digest_service.py` | Ambient daily "what changed" summary, built from precise deltas (not fuzzy recall) |
| `app/services/crypto_service.py` | AES-256-GCM encryption for sensitive `config.json` fields (email password, shared secret) using a local machine key |
| `app/api/files.py` | Workspace file browser/editor for the code editor panel, conversation → runnable project extraction, ad-hoc local file search |
| `app/api/graph.py` | Knowledge graph — real conversation/memory/document/project relationships already in the schema |
| `app/db/storage.py` | SQLite persistence, including the branching (parent/active) model |
| `app/db/migrations.py` | Ordered, idempotent schema migrations |

### Frontend module map

| File | Responsibility |
|---|---|
| `App.jsx` | Top-level state, SSE event handling, keyboard shortcuts, toasts, lock gate |
| `components/Composer.jsx` | Message input, attachments, mic, the mode picker (chat/search/research/agent/council/image) |
| `components/MessageBubble.jsx` | One message: markdown, tool-call cards (diff view + revert), plan card, generated images, branch switcher, citations |
| `components/Sidebar.jsx` | Conversation list (date-grouped) + unified search across chats/docs/memories |
| `components/Icon.jsx` | The single SVG icon system (replaced all emoji glyphs) |
| `components/LockScreen.jsx` | Passcode gate shown when the app is locked |
| `components/CommandPalette.jsx` | ⌘K palette |
| `components/SettingsPanel.jsx` | Every configuration surface |
| `components/ToastStack.jsx` | Background-event + desktop notifications |
| `lib/api.js` | All backend calls, shared SSE parser, host-derived API base, unlock header |

## Quick start

**Prerequisites:**
1. [Ollama](https://ollama.com) running locally with at least one model
   pulled (`ollama pull llama3.2`).
2. `ffmpeg` on your PATH (video frame/audio extraction).
3. Docker + Docker Compose (recommended), or Python 3.11-3.13 and Node
   18+ for a manual run (`./install.sh` checks these for you).

**Docker (recommended):**

```bash
docker compose up -d --build
```

Open `http://localhost:5173`. The backend listens on `:8420` and reaches
your host's Ollama via `host.docker.internal:11434` — see the note at the
top of `docker-compose.yml` if you'd rather run Ollama in its own
container instead. If Ollama shows unreachable from the container, check
that it's bound to more than `127.0.0.1` (`OLLAMA_HOST=0.0.0.0:11434
ollama serve`) — a common gotcha, not a Zenith bug.

**Manual — one-shot setup:**

```bash
./install.sh   # checks Python 3.11-3.13 / Node 18+, sets up backend venv +
                # deps and frontend deps + .env — prints the two run commands
```

Then, in two terminals:

```bash
cd backend && ./run.sh    # starts uvicorn on :8420
cd frontend && npm run dev
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
- **Resumable streams** — generation runs as an independent background
  task (`stream_registry.py`), not tied to the lifetime of the specific
  HTTP connection that started it. A dropped connection (wifi blip,
  laptop sleep) no longer kills the turn or loses the reply: the frontend
  automatically reconnects to `GET /api/conversations/{id}/chat/resume`,
  replays whatever was buffered while it was gone, and keeps streaming
  live from there; it gives up cleanly (not an infinite retry loop) once
  the run is confirmed gone (`404`). Verified live against real Ollama by
  cutting a connection mid-generation and confirming the reconnect
  produced the rest of the reply, correctly persisted.
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
  through a reply, Zenith retries once against your configured fallback
  model/role and tells you it downgraded.
- Add a keyword to `capability_keywords` (Settings, or directly in
  `data/config.json`) and any model containing it in its name gets
  auto-tagged — nothing is hardcoded to specific model names.
- **Hardware-aware recommendations** (Settings → Model routing) — each role
  card shows a "Use recommended: `<model>` (`<fit>`)" hint, computed by
  cross-referencing your installed, role-tagged models against the same
  hardware fit heuristic `/api/hardware` already used for the model
  cookbook. Real problem this solves: a model too big for your GPU doesn't
  error, it just spills onto CPU and can take minutes per reply or hang
  outright — this surfaces the fix (a smaller, still-capable model) instead
  of you having to notice the slowdown and guess.
- **Stuck-generation watchdog** (`stream_idle_timeout_seconds`, default
  120s) — a genuinely wedged model (the scenario above, or a truly hung
  Ollama process) used to hold the per-conversation lock forever, silently
  blocking every later message in that conversation behind a request that
  would never finish. Idle time (not total generation time — a long reply
  that's still actively streaming never trips this) beyond the configured
  limit cancels the request, releases the lock, and reports a clear error
  instead. The composer also shows an earlier, informational "taking longer
  than usual" hint at 15s, well before the hard cutoff.

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
  so Zenith remembers things you told it in a different chat.
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

**Tools** (a Claude-Code-class set):

| Tool(s) | What it does |
|---|---|
| `bash` | Run a one-shot shell command (cwd = the conversation's working dir) |
| `shell_start` / `shell_output` / `shell_write_stdin` / `shell_kill` / `shell_list` | **Persistent shell sessions** — start a dev server / watch mode / REPL that stays alive across tool calls, poll its output, feed it stdin, kill it. `bash` blocks until a command exits; these don't |
| `read_file` / `write_file` / `edit_file` / `list_dir` | File I/O. `edit_file` is a precise one-occurrence find-and-replace (same contract as Claude Code's Edit tool); fails loudly rather than guessing |
| `git` | **First-class git** — structured `status`/`diff`/`log`/`commit`/`branch` with parsed output, not raw git through `bash` |
| `run_checks` | Run the project's configured test/lint command and report pass/fail + output, so the agent verifies its own edits |
| `web_search` / `fetch_url` | Search the web / read a page's readable text |
| `browser_navigate` / `browser_click` / `browser_type` / `browser_get_text` / `browser_close` | **Real browser automation** — drive a headless Chromium (raw CDP) through JS-rendered pages, SPAs, and forms that `fetch_url` can't handle |
| `spawn_subagent` | **Delegate** a self-contained task to a nested, unattended sub-agent that reports back a summary |
| MCP tools | Anything advertised by a configured MCP server (see below) |

**Diff-preview + one-step undo.** Before a file edit runs, the approval card
shows a real unified diff (colored add/remove lines) instead of raw JSON
args, so you see exactly what will change. After it runs, a **Revert** button
restores the file to its prior contents (or deletes it if the edit created
it) — a per-call Cmd+Z.

**Autonomy has four modes** (Settings → Agent tools → Autonomy):

- **Manual** — every tool call pauses for your approval in the chat UI.
- **Semi-auto** — read-only calls (read/list/search/most bash/git-status)
  run immediately; anything that writes or executes ambiguously still asks.
- **Full-auto** — nothing pauses. Fast, and only as safe as your prompts.
- **Plan-first** — the model drafts a step-by-step plan; you approve it
  **once** in a plan card, then the whole plan runs unattended. Reject and
  nothing runs. This is the signature Claude-Code plan-mode experience.

**Per-project autonomy override** — a project can pin its own mode (the
bot icon next to a project's name in the sidebar), overriding the global
setting for every conversation in it: always plan-first in your dotfiles,
always full-auto in a scratch repo. Unset (the default) falls back to the
global `agent_mode` setting.

**Test/lint feedback loop.** Set a check command (e.g. `pytest -q`,
`npm test`) in Settings; the agent can call `run_checks` any time, and with
**auto-check** on it runs automatically after every file edit and the
pass/fail is fed back into the loop so the model fixes breakage on its own.

**Checkpoint / resume.** If a run hits its iteration cap without finishing,
the full loop state is saved to the DB; your next message resumes from
exactly where it stopped instead of starting cold. Survives a backend
restart.

Other properties:

- **Every tool call is audited** in a `tool_calls` table regardless of mode
  — nothing the agent does is invisible, including a sub-agent's own calls
  (tagged with their parent).
- **Per-conversation working directory** — bind a conversation to a real
  project folder (folder button in the header) and the agent's `bash` cwd +
  all relative file paths resolve against it automatically.
- **Agent-authored git commits never carry a `Co-Authored-By` trailer** —
  the `git commit` tool strips it, and commit messages go through argv (no
  shell injection).
- **No filesystem sandbox**, by explicit choice — tools operate on whatever
  the backend process can see. A real syscall sandbox was investigated and
  shelved (Docker's seccomp blocks the nested user namespaces bwrap/firejail
  need); see [`docs/NOT_BUILT.md`](docs/NOT_BUILT.md).
- **JSON-in-text tool calling**, not Ollama's native `tools` API — works
  with any chat model, at the cost that small models (roughly under ~4B
  params) often skip the protocol. Pin the relevant role to a bigger model
  for agent turns to work reliably. Verified directly: `qwen2.5-coder:3b`
  described its plan in prose; an 8B model correctly called `read_file` then
  `edit_file` and fixed a real bug in a real file.
- **Iteration cap**: 40 tool-call rounds by default (up to 200), after which
  the run checkpoints instead of just giving up.

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
Zenith hand-building each integration. Configure a server (command + args
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
- **Popular servers list** — the MCP ecosystem has no central registry, so
  Settings → Agent tools → MCP servers shows a short, hand-picked list of
  well-known, keyless servers (filesystem, fetch, memory, sequential-
  thinking, git) as clickable chips that pre-fill the add form. Deliberately
  a curated starting point, not an attempt at a live directory.

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

### Code editor panel

`app/api/files.py`. A file tree + multi-tab text editor for the
conversation's bound working directory (the same folder set via the
header's folder button for agent mode) — for quick edits that don't need
a full agent turn. Opens from the terminal icon in the header once a
working directory is bound.

- Strictly scoped to that directory: every path is resolved and rejected
  if it would escape it (`../`, absolute paths) — unlike agent mode's
  file tools, which intentionally allow the full filesystem, this is a
  direct, un-gated UI action, so it gets its own tighter boundary.
- Plain text only, 2MB cap per file — this is a lightweight editor for
  config/code/notes, not a full IDE (no language server, no syntax
  highlighting yet).
- **Git status/diff + run** — toolbar buttons show `git status`/`git
  diff` for the bound directory (reusing agent mode's own git runner)
  and execute the configured check command (Settings → Agent tools),
  streaming output into a pane below the editor — no model turn, no
  approval gate, just the same "run a command and see the result" loop
  a terminal gives you.
- ⌘S / Ctrl+S saves the active tab.

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

### Image generation

`image_service.py`. Optional **Image** mode in the composer, backed by a
local Stable Diffusion server (AUTOMATIC1111 / Forge / SD.Next — anything
speaking the standard `/sdapi/v1/txt2img` contract).

- Off until you point `image_gen_url` at your own SD server in **Settings →
  Connection** (e.g. `http://localhost:7860`, started with `--api`). No
  diffusion server is bundled — same "bring your own local model" posture as
  the Ollama dependency, kept free and local.
- Generated images render inline in the chat; click to open full size.
- Degrades gracefully: clear messages when it isn't configured or the server
  can't be reached, rather than a silent failure.

### Model management

Manage Ollama models from **Settings → Installed models** instead of the
CLI (`app/api/system.py` over Ollama's own API):

- **Pull** a model from the registry with a live progress bar.
- **Delete** an installed model.
- **Create a variant** from a base model — bake in a system prompt, or apply
  a fine-tuned **LoRA adapter** (uses Ollama's structured `create` API with
  `from` / `system` / `adapter`).

### Unified search

The sidebar search covers three sources in one query, grouped in the
results, not just conversation titles:

- **Conversations** — full-text over message *content* (SQLite FTS5).
- **Documents** — uploaded files, by filename and by their indexed chunk
  text.
- **Memories** — stored long-term facts, by content.

Document hits jump to their source conversation; memory hits open
Settings → Memory.

**Ad-hoc local file search** (`GET /api/search/local-files`, wired into
the [code editor panel](#code-editor-panel)'s file tree) complements
this for "I know roughly where this file is, I just haven't added it as
a watched folder": give it a directory path and a query, and it greps
that one tree right now (case-insensitive, filename and content), bounded
to 2000 files scanned / 50 matches so an unexpectedly large directory
can't hang the request. Nothing is indexed or remembered between
calls — a deliberately scoped alternative to a full OS-wide search index,
which would need a background crawler and a permissions model neither of
which exist here.

### Import from ChatGPT / Claude

`import_service.py`. **Settings → Data → Import** takes the
`conversations.json` from a ChatGPT or Claude data export, auto-detects which
it is, and creates a Zenith conversation per chat — original messages and
timestamps preserved, so your history from other tools isn't stranded.

### Folder watcher

`folder_service.py`. Point Zenith at a real directory (a notes vault, a
repo) in **Settings → Folders** and it periodically re-indexes matching
files (`.md`/`.txt`/`.py`/`.js`/`.ts`/`.json` by default) into RAG recall
— no manual upload per file. This is the single biggest "you can't get
this from a cloud chat tool" feature: your own notes become part of what
Zenith knows without you doing anything after initial setup.

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

**Settings → Data**. Everything Zenith knows about you, in a format you
can actually read and keep:

- **JSON** — complete machine-readable dump (every conversation with full
  message history, memories, personas).
- **Markdown** — one readable `.md` file per conversation, zipped, plus
  `memories.md` and `personas.md`. Good for archiving or reading outside
  Zenith entirely.

Both are plain stdlib (`json`/`zipfile`) — no new dependencies, runs
entirely against your own backend.

### Passcode lock

`app/api/lock.py`. Optional passcode gate (**Settings → Data**) so other
people using the same machine can't open your chats.

- **Real API-level enforcement**, not just a UI overlay: a live-checked
  middleware returns `423 Locked` for any `/api/*` request without a valid
  unlock token. The passcode is PBKDF2-hashed in config; the unlock token
  lives in `sessionStorage` (clears when the tab closes).
- Explicitly a **login gate, not at-rest encryption** — the SQLite file is
  still readable by anyone with filesystem access. Real encryption would
  need SQLCipher and would break FTS search; that tradeoff is documented,
  not silently made.

### Knowledge graph

`app/api/graph.py`. A grouped-column view (projects / conversations /
memories / documents) with lines for real relationships already in the
schema — memory extracted from a conversation, a document attached to
one, a conversation scoped to a project. Not a fabricated or inferred
graph, and not a physics-based force layout (that's a lot of moving
parts for "what connects to what") — click a conversation node to jump
to it, hover any node to highlight its edges.

### Self-improving memory

`memory_service.review_conflicts()`. Long-term memory only ever
accumulated before this — "Review for contradictions" (Settings →
Memory & persona) asks a model to scan enabled memories for pairs that
can't both be true ("uses fish shell" vs "uses zsh") and flags them for
you to dismiss, an explicit on-demand scan rather than automatic on
every save (an LLM pass over every memory isn't free enough to run
silently and constantly).

### Ambient daily digest

`digest_service.py`. Opt-in (Settings → Memory & persona → Daily
digest), off by default. Once a day, an unprompted "what changed"
summary is generated from precise deltas — files the folder watcher
re-indexed and memories added since the last digest — not fuzzy
similarity search, so it names actual changed files. Generate one
manually any time from the sun icon in the header.

### Automation rules + outbound webhooks

`events.py`, `webhook_service.py`, `automation_service.py` — one
internal event bus, two consumers (Settings → Automation):

- **Webhooks** — POST a JSON payload to a URL on your own machine when a
  real event happens: `digest_generated`, `schedule_completed`,
  `urgent_email`, `memory_conflict_found`, `folder_file_added`. Lets your
  own scripts react instead of polling the API.
- **Automation rules** — trigger → action on the same events, entirely
  in-app: "when a file lands in this folder, summarize it" without
  writing a webhook receiver. Actions are **prompt** (sends a message
  into a persistent per-rule conversation, chat/research mode only —
  never agent, same reason scheduled turns never run unattended agent
  mode) or **webhook** (a one-off URL for that rule specifically).
  `{event_data}` in a prompt is substituted with the triggering event's
  data.

### Task board

Todos (Settings-adjacent, opened from the header) now have a Kanban
**status** (`todo` / `in_progress` / `done`) alongside the original
checklist — switch to "Board" view to drag cards between columns; the
legacy done checkbox and the board status stay in sync either way you
change it.

### Interface

- **Command palette (⌘K)** — jump to any conversation, switch persona,
  run an action (new chat/theme/density/focus), or open a specific
  Settings section directly. Built fresh from current state each time it
  opens.
- **Quick actions** (Settings → surfaced via the snippets panel's "Quick
  actions" tab, `/api/quick-actions`) — your own named commands, one
  keystroke away in the command palette: a saved prompt template that
  either fills the composer for review or sends immediately
  ("auto-send"). The in-app analog to a plugin system — MCP already
  covers external tool plugins (see [MCP client support](#mcp-client-support)),
  this covers "my own reusable prompt" without writing an MCP server for it.
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
- **Pinned conversations + free-form tags** — pin a chat to float it above
  the date groups; tag any chat with your own labels (shown as chips in
  the sidebar), independent of the project grouping above.
- **Shareable read-only links** — generate a public, unauthenticated link
  to one conversation (title + messages only, no working directory or
  tags); revoke it any time. Bypasses the passcode lock by design (a
  link only works if you hand it out) but still respects shared-secret
  auth if that's enabled — see Safety model.
- **Prompt/snippet library** — save reusable message templates and insert
  them into the composer, separate from personas (which apply for a
  whole conversation, system-prompt level).
- **Ad-hoc 2-model compare** — the composer's mode picker has a
  **Compare 2** option that fans one message out to any two installed
  models side by side, without pre-configuring Settings → Council.
- **Context window indicator** — a rough usage bar appears in the
  composer once a conversation's estimated token count crosses 40% of
  the model's context window (chars/4 heuristic — a gauge, not an exact
  count).
- **Reasoning trace** — replies from models that emit `<think>` blocks
  (deepseek-r1, qwq, …) show a collapsible "Reasoning" toggle instead of
  dumping raw scratch-work into the visible answer.
- **One consistent SVG icon system** (`Icon.jsx`) — every emoji glyph was
  replaced with a single thin-stroke `currentColor` set, so the UI reads as
  a deliberate product rather than a generic "AI wrapper" across every OS.
- **Custom accent themes** — pick the primary accent (teal/violet/sky/
  amber/rose) in Settings → Appearance; re-hues the brand, buttons, and
  cursors in both light and dark, persisted per-device.
- **Desktop notifications** (opt-in) — a system notification when a reply
  finishes while the tab is backgrounded, or when a scheduled task runs.
- Calm, static background, real visual definition on assistant replies (a
  signal-colored left edge matching the routed model's capability color),
  softened text contrast for sustained reading.
- **First-run tour** — a one-time (localStorage-tracked) map of what exists,
  shown on first launch instead of dropping you into a blank app with 30+
  features and no orientation.
- **Accessibility pass** (real, not exhaustive — see caveats below) —
  conversation list items are real keyboard-focusable/announceable targets
  (`role="button"`, `Enter`/`Space` to activate, not just a mouse-only
  `<div onClick>`); five modal panels gained `Escape`-to-close and
  `role="dialog"`/`aria-modal` (the code editor and to-do panels
  deliberately excluded/scoped where Escape could silently discard
  in-progress typing); the Kanban board's drag-and-drop cards got a real
  keyboard alternative (a per-card "move to column" control), not just a
  fallback to the List view. Not claimed: a full WCAG audit hasn't been
  done, and this covers surfaces touched this pass, not the whole app.

## Desktop app

Zenith can be packaged as a native, double-click desktop app — no terminal,
no `docker compose`. The build has been run and verified on Linux; macOS /
Windows follow the same steps (see [`DESKTOP.md`](DESKTOP.md)).

- **Tauri v2 shell** — uses the OS's native webview (no bundled Chromium, so
  the shell binary is ~13 MB), and spawns the backend as a **sidecar**.
- **Frozen backend** — PyInstaller bundles the whole FastAPI backend into a
  single ~147 MB executable, so end users need neither Python nor Docker.
- **Persistence** — the SQLite DB lives in the OS app-data dir
  (`~/.local/share/dev.zenith.desktop`, `~/Library/Application Support/…`,
  `%APPDATA%\…`); closing the app never wipes anything.
- **Ollama stays external** (weights are too large to bundle). The app
  expects Ollama running on the host, same as the Docker deployment.
- Verified end-to-end: launching the built app spawns the backend sidecar,
  which binds `127.0.0.1:8420` and serves `/api/health` → 200. Linux builds
  produce a `.deb` and a portable `.AppImage`; Windows `.msi`/`.exe` builds
  on `windows-latest` via CI (`.github/workflows/ci.yml`, `desktop-windows`
  job) — see [Continuous integration](#continuous-integration).
- **System tray icon** — Show/Quit menu, so the app can live in the
  background instead of only existing as a window you have to keep open.
- **Global hotkey** — `Ctrl/Cmd+Shift+Z` toggles the main window's
  visibility from anywhere in the OS, not just when Zenith already has
  focus (`tauri-plugin-global-shortcut`). Both registered in
  `desktop/src-tauri/src/main.rs`'s `setup()`; either failing to register
  would abort the whole app's startup, so a successful launch is itself
  the verification that both work.
- **Auto-update** — a **"Check for Updates…"** tray item checks GitHub
  Releases (`tauri-plugin-updater`) and shows a native dialog either way.
  `.github/workflows/release.yml` builds, signs, and publishes Windows +
  Linux installers as a draft GitHub Release whenever a `v*` tag is pushed,
  generating the `latest.json` manifest the updater polls
  ([`tauri-apps/tauri-action`](https://github.com/tauri-apps/tauri-action)).
  The signing keypair's public half is committed (`tauri.conf.json`); the
  private half exists only as encrypted GitHub Actions secrets, never in
  the repo or on disk — see [`DESKTOP.md`](DESKTOP.md#auto-update) for the
  full setup and how to rotate it. Deliberately checks-and-tells-you rather
  than auto-installing — see that section for why.

## Browser extension

`extension/` — a minimal Manifest V3 extension (not published to any
store; install unpacked, see [`extension/README.md`](extension/README.md))
that sends the current page or a text selection into a new Zenith
conversation from wherever you're reading, instead of copy-pasting a URL
into the composer.

- **Send this page** — creates a conversation and asks Zenith to read and
  summarize the tab's URL; the extension doesn't extract page content
  itself, it hands the link to Zenith's existing URL-reading feature
  (`web_service.py`).
- **Send selected text** — grabs the current text selection via
  `chrome.scripting.executeScript` and sends it with the source URL for
  context.
- **Fire-and-forget by design** — the extension POSTs the turn and closes
  immediately without waiting for or displaying the reply; open Zenith
  itself to read it. This works because backend generation is decoupled
  from whichever connection started it (`stream_registry.py` — the same
  mechanism behind [resumable chat streams](#core-chat--multimodal)):
  verified live by cancelling the response body mid-request the exact way
  the extension does and confirming the full reply still generated and
  persisted correctly.
- **No build step** — three plain files (`manifest.json`, `popup.html`,
  `popup.js`), no bundler, no npm dependency; there's exactly one feature
  here, so a build pipeline would be pure overhead.
- Talks to `http://localhost:8420` by default (configurable in the
  popup, saved to the extension's local storage) via a static
  `host_permissions` grant in the manifest, which lets the extension's
  own popup/background pages bypass browser-side CORS for that origin —
  no backend CORS changes needed.

## Mobile & multi-device

One backend, many devices — shared access to a single instance (not
multi-master sync; see [`docs/NOT_BUILT.md`](docs/NOT_BUILT.md)).

- **Installable PWA** — web manifest + brand icons + `apple-mobile-web-app`
  meta, so the app installs to a phone's home screen and runs standalone. A
  network-first app-shell service worker registers in production builds.
- **Responsive layout** — on narrow screens the sidebar becomes an
  off-canvas drawer over a tap-to-close backdrop; header/composer adapt.
- **LAN / Tailscale access** — the frontend derives the backend URL from
  wherever it was opened (not hard-coded `localhost`), so browsing to
  `http://<host-ip>:5173` from a phone just works. Turn on the opt-in
  `cors_allow_lan` toggle to accept private-network + `*.ts.net` origins
  (verified: LAN origins allowed, public origins still blocked). Pair it
  with the passcode lock or shared-secret auth. See [`MULTIDEVICE.md`](MULTIDEVICE.md).

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
| Digest | `digest_enabled`, `digest_interval_hours` | `False`, `24` | Ambient daily "what changed" summary |
| RAG | `rag_enabled`, `rag_chunk_chars`, `rag_chunk_overlap`, `rag_top_k` | `True`, `1200`, `200`, `5` | Document/folder chunking + retrieval |
| Web | `web_search_backend`, `searxng_url` | `duckduckgo`, `""` | `"searxng"` + a URL swaps in your own SearXNG instance instead of DDG's HTML scrape |
| Web | `web_search_max_results`, `web_fetch_max_chars`, `web_fetch_timeout_seconds`, `web_fetch_max_urls_per_turn` | `5`, `4000`, `8`, `3` | Search/fetch limits |
| Agent | `agent_enabled` | `False` | Master switch |
| Agent | `agent_mode` | `manual` | `manual` \| `semi` \| `full` \| `plan` |
| Agent | `agent_max_iterations` | `40` | Tool-call cap per turn (1–200); checkpoints at the cap |
| Agent | `agent_subagent_max_iterations` | `8` | Step budget for a `spawn_subagent` delegation |
| Agent | `agent_check_command`, `agent_auto_check`, `agent_check_timeout_seconds` | `""`, `False`, `180` | Test/lint command, run-after-every-edit toggle, its timeout |
| Agent | `agent_command_timeout_seconds`, `agent_output_max_chars`, `agent_approval_timeout_seconds` | `60`, `4000`, `600` | Bash timeout, result truncation, approval-wait timeout |
| Images | `image_gen_url`, `image_gen_steps`, `image_gen_size`, `image_gen_timeout_seconds` | `""`, `20`, `512`, `180` | Stable Diffusion server URL + generation params |
| Research | `research_max_iterations` | `10` | Deep Research's step cap |
| Council | `council_models` | `[]` | Which installed models participate |
| Folders | `folder_scan_interval_seconds`, `folder_recall_enabled`, `folder_recall_top_k` | `600`, `True`, `3` | Background re-scan cadence + recall |
| Schedules | `schedule_check_interval_seconds` | `60` | How often due schedules are checked |
| Attachments | `upload_max_bytes`, `upload_orphan_ttl_seconds`, `attachment_ttl_hours` | `200MB`, `24h`, `72h` | Upload limits + cleanup |
| Auth | `auth_enabled`, `auth_shared_secret` | `False`, `""` | Shared-secret auth in front of the API |
| Lock | `lock_enabled`, `lock_pass_hash` | `False`, `""` | App-level passcode gate (set via Settings, not env) |
| CORS | `cors_allow_origins`, `cors_allow_lan` | localhost only, `False` | Allowed origins; `cors_allow_lan` also accepts private-net + `*.ts.net` |
| Ops | `log_level`, `request_timeout_seconds`, `prewarm_model_on_startup` | `INFO`, `600`, `False` | Structured logging, Ollama timeout, cold-start preload |

## Safety model

Zenith is a **personal, single-user tool** — the safety model reflects
that, not a multi-tenant SaaS product:

- **Agent mode is off by default.** You opt in explicitly, and pick an
  autonomy level (manual / semi / full / plan-first) that matches how much
  you trust it. Plan-first is the safest "let it run" option — you approve a
  whole plan up front instead of gating each step or gating nothing.
- **No filesystem sandbox** for agent tools, by design — see the Docker
  section above. The tradeoff is explicit: you get real practical power
  (editing your real code, running your real commands) in exchange for
  taking the guardrails off. Start with a scoped workspace mount if
  you're not sure.
- **Scheduled turns and automation rules can never use agent mode** —
  unattended + unsupervised + shell access is a combination this project
  deliberately refuses, for both the clock-triggered case (schedules) and
  the event-triggered case (automation rules' "prompt" action). Both are
  restricted to chat/research mode; the model can write you a report, not
  run commands nobody's watching.
- **MCP tools are always risky-classified** — you don't know what an
  external server's tool actually does, so it always gets the same
  approval gate as `write_file`, regardless of your agent mode setting.
- **Full audit trail** — every tool call (built-in or MCP) is logged with
  its args, risk classification, approval status, and result, regardless
  of autonomy mode.
- **Shared-secret auth** (`auth_enabled`) is available if you need to put
  this behind something other than `localhost`, but there's no
  multi-user/permission model — it's one shared secret for the whole API.
- **Passcode lock** gates the UI/API on a shared machine (a real `423`
  middleware, not UI theater) — but it's a login gate, **not** at-rest
  encryption. The database file (conversations, memories, documents)
  stays readable with filesystem access; real database encryption would
  need SQLCipher and would break FTS5 search, a tradeoff explicitly not
  taken on here.
- **Credentials are encrypted at rest** (`crypto_service.py`) —
  `email_password` and `auth_shared_secret` in `config.json` are
  AES-256-GCM encrypted using a local machine key
  (`data/.machine_key`, generated once, `0600` permissions), transparent
  to the rest of the app (every call site still just reads the plaintext
  value in memory). This is narrower than full database encryption on
  purpose: credentials are few, small, and don't need to be searchable,
  so they get real protection without the FTS5 tradeoff above. Copying
  `config.json` to another machine without the key file leaves those two
  fields unreadable ciphertext; it does not protect against another
  process running as the same OS user as Zenith on the same machine.

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
  A real syscall sandbox was investigated and shelved (Docker's default
  seccomp blocks the nested user namespaces bwrap/firejail need); details in
  [`docs/NOT_BUILT.md`](docs/NOT_BUILT.md).
- **Image generation needs your own Stable Diffusion server** — Zenith ships
  the integration, not a diffusion model. Off until you set `image_gen_url`.
- **No OS-level "computer use."** Browser automation (drive a web UI) is
  built; controlling arbitrary *native desktop apps* by screen capture +
  synthetic input is deliberately not — headless backend, platform-specific,
  and a severe security surface. See [`docs/NOT_BUILT.md`](docs/NOT_BUILT.md).
- **Desktop app: Linux built, macOS/Windows not.** The Linux `.deb` +
  `.AppImage` are built and verified here; the other platforms follow the
  same documented steps but haven't been run. Auto-update is scaffolded but
  needs a release pipeline to wire up.
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
pytest tests -q          # 73 tests, one requires Ollama reachable
```

```bash
cd frontend
npm run build             # production build + bundle-size check
```

The test suite covers storage/branching, the router, search, a full chat
round-trip against a real (or mocked) Ollama, the stream registry
(publish/replay/finish semantics for [resumable streams](#core-chat--multimodal)),
[automation rules + webhooks](#automation-rules--outbound-webhooks) (with a
fake `httpx` transport, no real network calls), the code editor's [ad-hoc
file search](#unified-search) and [project extraction](#code-editor-panel),
and the [encrypted-credential](#safety-model) round-trip (on-disk ciphertext,
in-memory plaintext, backward-compatible with pre-existing plaintext values).
One test (`test_app_boots_and_health`) requires Ollama to actually be
reachable — it's not a flake if it fails with Ollama stopped, that's the
expected contract of the health endpoint.

### Continuous integration

`.github/workflows/ci.yml` — three jobs on every push/PR: backend tests
(`pytest -q`), frontend build (`npm run build`), and a `desktop-windows`
job that freezes the backend with PyInstaller and runs `cargo tauri build`
on `windows-latest`, uploading the resulting `.msi`/`.exe` as workflow
artifacts. This is how Windows desktop builds are verified — see
[Desktop app](#desktop-app).

## License

[GNU AGPL-3.0-or-later](LICENSE). The short version: you can use, modify,
and self-host this freely — but if you run a modified version as a network
service others can use (a hosted "Zenith Cloud", say), you have to publish
your changes too. That's a deliberate choice, not a default: this project's
whole premise is "your own compute, no cloud middleman," and a permissive
license would let someone quietly rebuild the exact cloud-AI trust problem
Zenith exists to avoid. MIT/Apache-style "no strings attached" reuse isn't
the goal here.
