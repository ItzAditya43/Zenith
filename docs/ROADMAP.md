# Zenith roadmap — backlog

Ideas parked for later, picked up one at a time when there's a reason to.
Effort: **S** ≈ an afternoon · **M** ≈ a day or two · **L** ≈ a week or more.

## Core — makes the main loop better

| # | Feature | Why | Effort |
|---|---|---|---|
| C3 | **Type errors from language servers** | Quick checks after edits are built (syntax, undefined names). Real type errors for TypeScript, Rust and typed Python need a language server per language (tsserver, rust-analyzer, pyright). | L |

## Experience

Zenith stays chat-first: these make the code side panel pleasant, not an IDE.

| # | Feature | Why | Effort |
|---|---|---|---|

## Platform & distribution

| # | Feature | Why | Effort |
|---|---|---|---|
| P1 | **Notarized macOS builds** | Needs an Apple Developer ID; removes the right-click → Open step. | S (+ account) |
| P2 | **Windows code signing** | SmartScreen warns on unsigned installers. | S (+ certificate) |
| P3 | **Encrypted sync between your machines** | Multi-master sync with conflict resolution; today devices share one backend. | L |
| P9 | **Tested on more setups** | Hand-verified on one Linux laptop. A support matrix (OS, GPU, Ollama version) filled in from real reports, plus the Windows/macOS smoke runs. Parked 2026-11-13. | ongoing |

## Known follow-ups

- Agent evals on real local models (`cd backend && python -m evals agent --model <model> --repeat 3`) — run by hand; automated runs of a shell-driving agent are blocked by design.
- Two commits in the 0.10.0 history have messages that don't match their contents (content is correct; fixing needs a history rewrite).

## Product direction — capability backlog

This section captures the next product ideas requested for Zenith. The numbers
are stable references for discussion, not a strict delivery order. Zenith
already has some foundations (chat summaries, persistent memories,
cross-conversation retrieval, image attachments, and video frame/audio
extraction); items below describe the gaps and extensions to pursue. Effort is
roughly **S** ≈ an afternoon, **M** ≈ a day or two, **L** ≈ a week or more,
and **XL** ≈ a multi-week design and implementation effort.

### Core coding-agent workflow

1. ~~**Background agent runs**~~ — **Done (1.2.6):** sidebar → Tasks queues agent work that runs in the backend with the window closed; persisted live log, approvals, cancel, restart recovery, desktop and ntfy notifications. Original note: Queue work, keep it running after the UI closes,
   and notify when it finishes. Provide run status, logs, cancellation, and a
   review step for proposed changes. Build on existing resumable streams,
   checkpoint/resume, worktrees, schedules, and notifications. **M–L**.
2. **Language-server diagnostics** — Integrate optional TypeScript, Rust, and
   Python language servers. Surface diagnostics after edits and let the agent
   use those errors in a bounded repair loop. Keep this in the chat-first
   workspace rather than growing a full IDE. **L** (existing roadmap item C3).
3. **Code navigation in the workspace** — Add symbol search, go-to-definition,
   find references, and diagnostics to the existing editor. Use language-server
   support where available and retain text-search fallbacks. **M–L**.
4. **Project code context** — Maintain a searchable project index of code,
   architecture decisions, and recent agent runs; retrieve only relevant,
   cited snippets into coding conversations. Reuse the existing RAG and
   project/folder concepts. **M–L**.
5. ~~**Agent run review screen**~~ — **Done (1.2.6):** a Review button on every agent reply and task shows changed files with diffs, commands and checks, and the timeline, with Accept / Undo all / Continue. Original note: Present changed files, diffs, checks, and tool
   activity together, with accept/revert/continue controls. Preserve the
   existing per-hunk diff approval and undo semantics. **M**.

### Conversations, models, and sharing

6. ~~**Conversation organization**~~ — **Done (1.2.6):** Manage chats (sidebar or palette) filters by title, tag and state, saves filters, and pins, tags, archives, restores or deletes in bulk; archived chats leave the sidebar. Original note: Add tags, pinned chats, saved filters, and
   bulk archive/delete controls to the existing search and sidebar. **S–M**.
7. ~~**Reusable prompt workflows**~~ — **Done (1.2.6):** quick actions take fields ({{file}}, {{tone|friendly}}, auto {{date}}/{{time}}), are validated on save, ask for their fields when run, and travel in packs. Original note: Turn quick actions into parameterized
   templates (for example, “review this diff”), with validation and import /
   export. **M**.
8. ~~**Answer and routing feedback**~~ — **Done (1.2.6):** thumbs and a "wrong model" flag on replies; Settings → Model routing shows per-model totals and recent wrong-model picks; nothing is applied automatically. Original note: Let users rate answers and flag poor model
   choices; show the feedback in model comparisons and routing diagnostics.
   Any automatic learning should be inspectable and reversible. **M**.
9. ~~**Model comparison runs**~~ — **Done (1.2.6):** Compare models (palette or Model routing) runs one prompt on 2–4 models at once with time to first word, total time and speed, saves each comparison and lets you pick a winner. Original note: Send the same prompt to selected models, show
   latency, speed, and side-by-side output, and save comparisons. **M**.
10. ~~**Safe conversation sharing**~~ — **Done (1.2.6):** sharing opens a preview that finds emails, phone numbers, keys and tokens, IPs and home paths; you choose what to hide and which messages to include, and the link serves a frozen redacted snapshot (or download it as Markdown). Original note: Add a previewable export/share flow with
    explicit redaction of sensitive text and attachments. Keep it opt-in and
    local-first. **M**.
11. ~~**More import/export formats**~~ — **Done (1.2.6):** imports Open WebUI exports, OpenAI-style message lists and Markdown transcripts (including Zenith's own export) alongside ChatGPT/Claude, tags each chat with its source and skips ones already imported; Markdown/JSON export can include or leave out models, times, tags and attachment names, per chat or all at once. Original note: Add common assistant and chat formats,
    plus Markdown/JSON export controls for attachments and metadata. Preserve
    the existing deduplication and provenance behavior. **S–M**.

### Research, knowledge, and personal workflows

12. **Research workspaces** — Save sources, notes, claims, and reports together;
    show which sources support claims and allow users to rerun searches for
    updates. **M–L**.
13. ~~**Source freshness and quality cues**~~ — **Done (1.2.6):** web sources are numbered and labelled by kind (docs, code, forum, wiki, paper, news, blog, video) with published/updated dates from the page and when they were checked; old pages are flagged; the model is told to cite [n] for retrieved facts and to say when it's using its own knowledge. Original note: Show publication/update date,
    source type, and last-checked time; distinguish retrieved facts from model
    inference. **M**.
14. ~~**Knowledge graph exploration**~~ — **Done (1.2.6):** search (keeps what matches connect to), type filters, an only-connected toggle, curved links that light up on hover, and a side pane listing each item's connections with Open (chat, memory browser, or document preview). Original note: Filter and search graph entities and
    open the underlying conversation, memory, or document from each node.
    Reuse the real relationships already stored in Zenith. **M**.
15. ~~**Knowledge cleanup**~~ — **Done (1.2.6):** Knowledge cleanup (palette or Memory → Clean up) proposes merging near-duplicate memories, turning off unused ones, removing index entries whose source is gone, dropping documents indexed twice and reindexing changed files — with the evidence for each, applied only on your say-so, and every batch undoable. Original note: Find duplicate or stale indexed sources and offer
    reviewable memory updates before they affect future answers. Include
    provenance and undo. **M**.
16. **Calendar interoperability** — Add calendar import/export or provider
    connections, plus conflict checks before creating or changing events.
    **M–L**.
17. **Email workflows** — Extend IMAP/SMTP with inbox triage and reply drafts
    that require review before sending; add reusable filters for common tasks.
    **M**.
18. **Task-linked automations** — Connect tasks, schedules, and automation
    rules so scheduled work can create/update tasks and report changes.
    **M**.
19. ~~**Notification controls**~~ — **Done (1.2.6):** one history of everything that notifies (bell in the header, searchable, filter by kind), per-kind pop-up switches, quiet hours that also hold back ntfy pushes, and a retention setting. Original note: Add per-event preferences, quiet hours, and a
    searchable notification history for background runs, schedules, and
    automations. **S–M**.

### Platform and ecosystem

20. **Encrypted sync across independent installs** — Synchronize separate
    Zenith backends with real conflict resolution, version history, and
    recovery. This is an XL effort and must not use silent last-write-wins
    merging (see `NOT_BUILT.md`). **XL** (existing roadmap item P3).
21. ~~**Prebuilt Docker images**~~ — **Done (1.2.5):** the release workflow
    publishes versioned amd64/arm64 images to GHCR; compose pulls them.
22. ~~**Shareable feature packs**~~ — **Done (1.2.6):** export quick actions, personas and automation rules as a versioned `zenith-pack` file; import shows a preview with duplicates, problems and what each item may do, and imported rules start switched off. Original note: Package quick actions, personas, and
    automation rules for import/export, with a manifest, versioning, and a
    clear permission preview. **M** (existing roadmap item P8).
23. **Release signing and platform validation** — Add macOS notarization and
    Windows code signing, plus a support matrix and hands-on smoke checks
    across operating systems, GPUs, and Ollama versions. **S + credentials /
    ongoing** (existing roadmap items P1, P2, P9).

### Memory and multimodal upgrades

24. ~~**Conversation compaction with continuity**~~ — **Done (1.2.5):** structured state (goals, decisions, constraints, facts, files, open questions, next actions) with source links, inspect/edit/pin/regenerate from the chat menu → Conversation state; pinned items survive edits and regeneration. Original note: Upgrade the existing
    long-chat summary into a durable, inspectable conversation state: goals,
    decisions, constraints, important facts, files, open questions, and next
    actions, each tied to the source messages it summarizes. Compact before
    context limits, retain recent turns verbatim, and rebuild or invalidate
    summaries after edits or branch changes. Let the user inspect, edit, pin,
    or regenerate the summary. **M**.
25. ~~**Inter-chat memory and memory management**~~ — **Done (1.2.5):** scopes (everywhere / project / one chat), source message links, confidence, use counts, approval for uncertain or sensitive facts, a never-remember list, and a memory browser (search, edit, re-scope, merge, turn off, forget, export); replies show the memories they used. Original note: Expand existing memory and
    cross-conversation recall with explicit scopes (global, project, and
    conversation), provenance links, confidence/recency, and exclusions.
    Provide a memory browser to search, edit, merge, disable, forget, and
    export memories; show which memories were used in a reply; and support
    approval for sensitive or uncertain saves. Retrieval should be relevant
    rather than injecting every memory into every turn. **M–L**.
26. **Richer image and video understanding** — Improve existing image and
    sampled-frame/audio processing with user-selectable video sampling,
    timestamps, scene descriptions, OCR for screenshots, and synchronized
    visual/audio summaries. Let users ask questions about a frame or time
    range and cite the relevant timestamp. Keep model capability and local
    versus remote processing visible, with local processing as the default.
    **M–L**.

### API providers and integrations

27. **Provider setup that just works** — Improve the existing API provider
    flow with a guided connection check: validate the endpoint and key, list
    available models, report supported capabilities (vision, tools, streaming,
    embeddings), and explain the next step when a check fails. Keep credentials
    encrypted and never echo them back. Include local OpenAI-compatible servers
    as a first-class no-key path. **M**.
28. **Per-provider controls and spend visibility** — Add per-provider enable /
    disable, model allow-lists, role eligibility, and optional monthly or
    per-session spend limits where provider usage data is available. Show
    clearly labeled estimates when costs must be calculated locally; do not
    imply exact billing data if the provider does not expose it. **M–L**.
29. **Provider-aware model routing** — Make capability and privacy choices
    explicit in routing: local-only, allow selected remote providers, or use
    remote only when manually selected. Explain the route before a request and
    show which provider/model handled it afterward. Add provider failover only
    when the user has explicitly configured eligible fallback models. **M**.
30. **Stable public API and client examples** — Document and version the
    backend API, publish OpenAPI examples and a small Python/TypeScript client
    for common workflows (chat streaming, files, models, and events). Make
    authentication, permissions, rate limits, and API-key rotation clear
    before promoting automation use. **M–L**.

### Installation and a calmer first run

31. **One-path install and first launch** — Make the recommended route obvious
    for desktop, Docker, and manual installs; detect prerequisites and give
    copyable, platform-specific fixes. After install, run a short readiness
    check for the backend, Ollama or a chosen API provider, model availability,
    storage, and optional ffmpeg. Let users start with an already available
    provider or skip model downloads and finish setup later. **M–L**.
32. **Optional, low-pressure onboarding** — Replace the compulsory-feeling
    first-run tour with a dismissible “Get started” checklist in the app. The
    first screen should let people start chatting immediately, with a few
    optional next steps (connect a model, try a file, explore agent mode).
    Keep “Skip for now,” “Don’t show again,” and “Show tips” visible; do not
    make users configure API keys, enable agent mode, choose a persona, answer
    an audience question, or step through every feature before using chat.
    Offer short contextual tips only when relevant, and replay the full tour
    from Help/Command Palette. **S–M**.
33. **Progressive setup and clear choices** — Split setup into “ready to chat”
    and optional capabilities. Explain local Ollama versus remote API models,
    privacy, and possible provider charges in plain language at the moment a
    user chooses them. Never preselect remote routing, paid features, voice
    capture, desktop control, or agent autonomy. Save progress so a user can
    return to setup without losing the ability to use the app. **M**.

## Architecture inspiration to study

These are patterns worth learning from, not dependencies or a plan to copy a
closed product. Any adoption should fit Zenith's local-first, single-user
design and be checked for license, maintenance, and privacy implications.

- **Claude Code** — Study its documented project instructions and persistent
  memory workflow, plus explicit context compaction. The useful Zenith lesson
  is to separate durable project guidance from chat history and make compaction
  resumable and editable. See [Claude Code memory docs](https://code.claude.com/docs/en/memory)
  and [context-window troubleshooting](https://code.claude.com/docs/en/troubleshooting).
- **OpenAI Codex** — Study image inputs, project instructions, task continuation,
  and the agent harness / sandbox boundary. For Zenith, the practical visual
  lesson is to attach images with appropriate fidelity and preserve their
  relationship to code, diffs, and the active task. See [Codex image inputs](https://developers.openai.com/codex/cli)
  and [Codex agent architecture](https://developers.openai.com/api/docs/guides/agents-api/architecture).
- **Google Antigravity** — Its public docs describe a loop of inspect → plan →
  act → observe → verify, with artifacts and asynchronous subagents. Study
  those ideas for evidence-backed run review and background work, while
  retaining Zenith's explicit approval model. See [how agents work](https://antigravity.google/docs/learn/how-agents-work)
  and [subagents](https://antigravity.google/docs/subagents).
- **OpenHands Software Agent SDK** — Study the separation between agent core,
  runtime, event stream, and UI/API. This could help Zenith keep one execution
  engine behind its web, desktop, and future background-run surfaces. See
  [SDK architecture](https://github.com/OpenHands/docs/blob/main/sdk/arch/overview.mdx)
  and the [OpenHands SDK paper](https://arxiv.org/abs/2511.03690).
- **Letta** — Study explicit memory blocks, archival memory, and memory
  maintenance. The useful idea is a memory system users and agents can inspect
  and curate, rather than an opaque vector store. See [Letta memory docs](https://docs.letta.com/configuration/memory/).
- **Aider and Continue** — Study repository mapping, concise project context,
  provider abstraction, and small composable workflows. These are useful
  references for Zenith's project indexing and model-agnostic editor/agent
  architecture: [Aider](https://github.com/Aider-AI/aider) and
  [Continue](https://github.com/continuedev/continue).

### Suggested implementation sequence

1. Make project instructions, compacted chat state, and inter-chat memory
   inspectable and provenance-linked (24–25).
2. Improve multimodal attachments and timestamped video understanding (26),
   starting with the existing local frame/audio pipeline.
3. Complete background agent runs and richer run review (1, 5), then add
   diagnostics and project code context (2–4).
4. Improve knowledge, research, personal workflows, and organization (6–19).
5. Deliver distribution and ecosystem improvements (20–23), with independent
   encrypted sync treated as a separate architecture project.
6. Make provider configuration reliable (27–30) and simplify installation and
   first run (31–33); keep optional features discoverable without blocking the
   first useful chat.
