# Zenith — feature-by-feature improvement plan

> **Status (v1.2.8, 2026-11-27).** Most of this plan has shipped. See CHANGELOG
> 1.2.5–1.2.8 and ROADMAP.md for what changed in each area. Still open, by design or
> because they need things outside the code:
> - **Independent sync between devices** (§31/§32, ROADMAP #20) is a separate
>   architecture project, not started.
> - **Signed and notarized installers** (§31) are wired into the release workflow and
>   switch on once signing certificates are added as repository secrets. Until then,
>   builds are labelled unsigned.
> - **At-rest encryption** (§23) is explained in docs/SUPPORT.md, not built. Use
>   full-disk encryption.
> - **Hand-verifying each platform** (§31) (install, upgrade, sleep/resume, tray, hotkey)
>   needs a real macOS and Windows machine. CI only compiles those builds.

This plan audits the features documented in [`FEATURES.md`](FEATURES.md) and
records what would make each one more dependable, understandable, and useful.
It is a planning document, not a claim that these changes are already built.
Zenith already has substantial functionality, so each section starts from the
current behavior and focuses on gaps, edge cases, and worthwhile extensions.

The aim is **reliable before broader**: each feature should explain its state,
fail clearly, preserve user data, and behave consistently across local models,
API models, desktop, browser, and mobile where supported. Optional or remote
capabilities should be discoverable without blocking basic chat.

## 1. Core chat and multimodal input

- Make conversation streaming robust to app refreshes, laptop sleep, backend
  restart, duplicate reconnects, and cancellation. Show a clear state for
  reconnecting, stopped, failed, and completed turns; avoid duplicate messages.
- Improve attachment previews, progress, size/type errors, retry, and removal
  before send. Keep the source filename and extraction status visible.
- **Images:** support multiple images and high-resolution detail selection;
  improve OCR, diagrams, screenshots, and image comparison. Display which
  vision-capable model will receive them and whether it is remote.
- **Video:** expose frame sampling density and timestamps; let users ask about a
  time range or frame; combine scene descriptions with transcript/audio and
  cite the timestamp. Keep processing limits and failed extraction visible.
- Improve audio attachment handling and transcript review; offer a way to
  correct speech-to-text before sending when the transcription is uncertain.
- Make context length and token estimates more accurate per provider/model;
  explain what older conversation context has been summarized or omitted.
- Add reliable message retry, stop, regenerate, copy, export, and attachment
  download behavior on narrow screens and after reconnects.

## 2. API model providers

- Create a provider connection check for endpoint reachability, key validity,
  model listing, and supported features (streaming, vision, tools, JSON output,
  embeddings). Provide actionable errors without exposing secrets.
- Make API model capability labels explicit; don't assume every
  OpenAI-compatible endpoint implements the same features or request shape.
- Add per-provider model allow-lists, enable/disable, role assignment, and
  explicit local-only / selected-remote / manual-only routing controls.
- Show provider and model on each answer, remote/local status before sending,
  usage when available, and a clearly labeled cost estimate when usage pricing
  is known. Never imply estimated cost is the provider's invoice.
- Support user-defined fallback chains only by explicit configuration; explain
  when a retry crosses from local to remote or between providers.
- Test key rotation, provider removal, malformed responses, rate limits,
  timeouts, outages, and model renames. Ensure old keys are erased on update.
- Document the provider API and publish a small set of working examples for
  OpenAI-compatible endpoints and Anthropic, including privacy and billing
  implications.

## 3. Model routing and model management

- Add a “why this model?” detail panel that exposes modality, role, local/remote
  status, context fit, confidence, fallback, and any user override in plain
  language.
- Improve capability detection beyond name keywords with provider metadata,
  user correction, and a small optional capability probe; always allow manual
  override and show uncertain classifications.
- Let users set a global local-only policy and per-role provider/model allow
  lists. Keep remote inference opt-in and visible at the point of use.
- Make failover behavior predictable: report what failed, what model was tried
  next, and whether the request may have been sent to a different provider.
- Improve model install/pull flows with cancel/resume, disk-space estimate,
  download size, compatible quantization suggestions, and recovery from a
  partial pull. Explain consequences before delete.
- Keep recommendations hardware-aware but show uncertainty and actual observed
  latency/RAM/VRAM where possible. Avoid stale curated model suggestions.
- Give users a simple model compatibility check for chat, code, vision, tools,
  and embeddings before they assign a model to a role.

## 4. Memory, chat compaction, and personalization

- Improve existing chat summaries into **inspectable compaction state** with
  goals, decisions, constraints, files, open questions, and next actions.
  Preserve recent turns verbatim, cite the message range summarized, and
  rebuild after edits, branch changes, or summary corrections.
- Improve cross-chat recall with global, project, and conversation scopes,
  source links, relevance controls, exclusions, and a visible “used in this
  answer” explanation.
- Add a unified memory manager to search, create, edit, merge, disable, forget,
  export, and restore memories. Show provenance and last-used information.
- Let users choose whether durable facts are saved automatically, require
  approval, or are never saved. Treat sensitive details conservatively.
- Make memory conflicts reviewable with proposed resolution and source
  evidence; never silently overwrite an older fact with a guessed update.
- Separate user preferences, project instructions, chat summaries, and
  retrieved conversation excerpts so each has a clear scope and lifecycle.
- Make memory extraction/retrieval failures visible in diagnostics without
  interrupting ordinary chat.

## 5. Web search, URL reading, and source handling

- Add search result freshness, source domain/type, and retrieval timestamp;
  label claims that are model synthesis versus directly supported by a source.
- Improve source reading for long pages, PDFs, blocked pages, redirects, and
  changing site layouts; explain when only partial content was available.
- Keep SSRF protections and private-network restrictions consistent across
  search, URL fetch, browser automation, webhooks, and MCP tools.
- Make citations stable and useful: open the exact source/section, preserve
  source metadata on export, and flag unsupported or uncited report claims.
- Add optional user-selected search providers without requiring an account for
  the basic self-hosted path; document when a query leaves the machine.
- Improve YouTube/video handling beyond captions-only: describe visual frames
  with timestamps where a vision model is available and explicitly report
  missing captions or failed frame/audio extraction.

## 6. Agent mode and tool execution

- Improve model reliability with schema-constrained tool arguments across
  providers, tool-call repair with strict bounds, and clear handling when a
  model answers in prose instead of invoking a tool.
- Make approval cards easier to understand: show exact command/file scope,
  effect, risk, and whether the action can be undone before approval.
- Ensure cancellation, timeout, backend restart, and connection loss leave a
  recoverable run state and never strand a conversation lock.
- Strengthen path and symlink boundary checks; show the effective workspace,
  sandbox type, network access, and permitted paths before an agent run.
- Improve shell output limits, persistent-session cleanup, command timeout,
  process termination, and recovery of orphaned child processes.
- Make plan-first plans editable and keep actual tool actions tied to approved
  plan steps. If the plan changes materially, request approval again.
- Make undo semantics explicit for writes, deletes, git actions, and commands;
  record which actions cannot be rolled back.
- Add a run review page with complete event history, diffs, checks, citations,
  and final status; allow safe resume and branch/worktree cleanup.
- Evaluate agent success on representative tasks and common local models;
  publish model/tool reliability results rather than relying on anecdotes.

## 7. Desktop control

- Improve platform coverage and report supported actions per OS/compositor;
  never show controls that cannot work on the current system.
- Keep the opt-in state, listening/capture state, target window, and pending
  approval obvious. Provide a fast stop/panic control.
- Require explicit confirmation for consequential actions, handle focus changes
  safely, and maintain the existing protection around password managers.
- Improve accessibility-tree targeting and OCR confidence reporting; avoid
  clicking when the target is ambiguous and ask the user to choose.
- Record a reviewable action log with undo guidance where possible. Do not
  imply that arbitrary desktop actions are reversible.
- Add end-to-end tests on real supported desktops before claiming platform
  support; distinguish CI compilation from hands-on verification.

## 8. Deep Research

- Show research plan and let users edit/add/remove subquestions before search.
- Track source coverage per subquestion, deduplicate sources, and preserve
  citations through synthesis and export.
- Distinguish direct source evidence, conflicting evidence, and model inference;
  identify claims that lack a citation.
- Support pause, resume, cancel, and continuation after a browser/backend
  reconnect; surface per-source errors and partial reports.
- Add bounded search/read budgets and explain when the report is incomplete due
  to limits, unavailable pages, or provider failure.
- Save research into a project/workspace with sources and notes; optionally
  re-run searches to refresh a report while showing what changed.

## 9. MCP client support

- Add a connection/test view showing server state, available tools, schemas,
  last error, and permissions before the tools enter an agent session.
- Require clear approval for installing/launching commands and sending secrets
  through environment variables. Redact secret values from logs and UI.
- Make tool provenance visible in approval and run history, including server
  name, tool name, and arguments/results with sensitive fields redacted.
- Handle server startup failure, timeout, malformed tool output, disconnect,
  and version incompatibility without blocking unrelated chat.
- Add per-server enablement, tool allow/deny controls, and a one-click stop.
- Keep gallery metadata and install sources auditable; show package/command
  being installed and never imply an MCP server is trusted just because listed.

## 10. Zenith as an MCP server

- Document supported tools, schemas, local permissions, authentication, and
  how to run/connect the server for each supported MCP client.
- Add read-only and write-capability distinctions, per-tool allow-lists, and a
  clear confirmation model for operations that change notes or tasks.
- Add robust pagination and result limits for memories, documents, notes, and
  todos; include source metadata and stable identifiers.
- Validate behavior with multiple MCP clients and protocol versions; make
  errors actionable and keep server logs free of credentials.

## 11. Council and model comparison

- Show each model's status, latency, failure, and cost/remote status as results
  stream; allow cancellation of one or all members.
- Prevent a failed/slow member from blocking completed responses; offer a
  clear timeout policy and partial-result state.
- Add optional synthesis only after showing raw model responses, and cite which
  model contributed each synthesized point.
- Preserve per-model privacy and routing constraints; do not fan out to remote
  models unless the user explicitly selected them.
- Save comparisons with prompt, model versions, timing, and user ratings for
  later evaluation.

## 12. Conversation branching and history

- Make branch tree discovery, naming, compare, switch, and delete straightforward
  without losing inactive history by accident.
- Explain which branch is active and which summary/context is valid after a
  message edit or regeneration.
- Preserve attachment references and tool provenance across branch operations.
- Add recovery for interrupted edits, migrations, or stale branch pointers;
  validate branch integrity on startup and expose repair diagnostics.

## 13. Live artifacts and preview

- Tighten sandbox policy for previews; validate that generated previews cannot
  access Zenith APIs, local files, or parent-page state.
- Show supported file types, preview limitations, and execution state; provide
  a visible stop/reload action.
- Improve error reporting for compile/runtime failures and preserve source code
  when a preview fails.
- Add optional browser-size presets and screenshot comparison for UI work, with
  explicit user-initiated capture.

## 14. Workspace drawer, editor, terminal, and Git

- Make workspace root, sandbox, and filesystem access visible before edits or
  terminal commands, especially in Docker where host files need a mount.
- Improve editor dirty-state handling, save/reload conflicts, large-file
  behavior, syntax support, and keyboard accessibility.
- Add safer terminal lifecycle controls: cancel, timeout, restart, clear output,
  and cleanup when a workspace closes.
- Make Git state refresh dependable; handle detached HEAD, conflicts, ignored
  files, large diffs, and push/auth errors with clear next steps.
- Separate agent-created changes from pre-existing user changes in review and
  undo flows; never revert unrelated edits.
- Improve worktree creation/cleanup around branch collisions, uncommitted
  changes, and failed setup; retain recovery instructions.
- Add source-control checks and workspace readiness checks before handing an
  issue or PR task to the agent.

## 15. Document upload, retrieval, and editing

- Improve extraction feedback by file/page: show what parsed, skipped, or
  failed; provide OCR as an optional path for scanned PDFs/images.
- Add format-aware retrieval and citations (page, heading, row, or source
  location), plus duplicate detection and stale-index cleanup.
- Add document size/page limits with clear pre-upload warnings and retry.
- Preserve original documents and metadata; show diffs for edits and make
  generated outputs clearly separate from the source.
- Expand editing formats only when the implementation can preserve layout and
  formatting; do not silently round-trip lossy PDF/DOCX extraction.

## 16. Image generation

- Add a setup test for the configured generation server and clearer support for
  server variants, model availability, and common API errors.
- Expose size, aspect ratio, seed, and other supported options without
  overwhelming the basic prompt flow.
- Add image editing/reference-image flows only when the backend supports them;
  preserve originals and make generated assets easy to save/manage.
- Show whether generation is local or remote, retain prompt/settings with the
  result, and provide clear progress/cancel behavior.

## 17. Model downloads and library

- Make hardware estimates conservative and explain that actual performance
  varies with context length, quantization, concurrent work, and GPU sharing.
- Add cancel/resume and disk-space handling; show model size and source before
  download and confirm before destructive deletion.
- Verify that model list/search/catalog data is current and label curated
  suggestions with update date and compatibility evidence.
- Make imported/custom model variants discoverable and removable without
  confusing them with their base model.

## 18. Unified search and local file search

- Add filters by source, project, date, file type, and conversation; preserve
  useful search history locally with a clear clear-history action.
- Improve result snippets, ranking explanations, and jump-to-source accuracy.
- Make indexing status and stale/failed sources visible; add reindex controls.
- For local file search, show the exact searched directory and limits and
  handle permission errors, symlinks, and large files safely.

## 19. Import from other assistants

- Add import preview with chat count, message count, attachment coverage, and
  duplicate estimate before writing to the database.
- Preserve timestamps, roles, titles, branches where supported, and original
  metadata; report fields the source format cannot preserve.
- Make imports resumable and transactional so a failure does not leave a
  confusing half-import; provide undo/delete for the imported batch.
- Add additional documented formats based on real user demand and fixture
  samples; avoid silently accepting malformed export files.

## 20. Watched folders and RAG indexing

- Add per-folder include/exclude patterns, file-size limits, supported-format
  preview, and a pause/resume switch.
- Show scan progress, last successful scan, errors, indexed counts, and a way
  to reindex a file or folder.
- Detect file moves/renames and avoid duplicate or stale chunks; handle
  concurrent edits while scanning.
- Offer explicit privacy boundaries and folder-root validation; never scan
  outside the selected folder due to symlinks without telling the user.
- Improve chunking and retrieval evaluations on code, notes, tables, and
  long-form documents; expose retrieval sources for correction.

## 21. Schedules and recurring turns

- Add friendly schedule controls (daily/weekly/custom time) and timezone/DST
  clarity; keep interval mode for advanced use.
- Show next run, last run, missed runs, model/provider, and exact mode; notify
  on repeated failure.
- Add pause/resume, run-now, retry, and safe deletion with history retention.
- Keep unattended agent execution disabled unless a separate, explicit,
  reviewable security design is introduced; scheduled chat/research should
  identify partial results and source changes.

## 22. Data export, backup, and migration

- Add one-click backup/restore with integrity check, backup timestamp, version,
  attachment coverage, and a restore preview.
- Make exports include/omit attachments, secrets, settings, and metadata with
  clear defaults. Never export credentials unless a separately protected
  mechanism is deliberately designed.
- Test import/export round trips across versions and recover cleanly from
  corrupt/partial archives.
- Add migration status and rollback/recovery strategy for database schema and
  configuration upgrades.

## 23. Passcode lock and security

- Provide passcode change/reset flow, lock timeout, attempt backoff status, and
  clear device/session behavior; avoid locking users out without recovery info.
- Document precisely what the passcode does not encrypt. Evaluate at-rest
  database/attachment encryption as a separately scoped design.
- Audit auth consistently across REST, SSE, WebSocket/stream resume, MCP, and
  shared links. Add session revocation and secret rotation.
- Add CSRF/host/origin, SSRF, path traversal, upload, archive, and dependency
  security reviews to release checks.
- Make security-sensitive settings and externally reachable network bindings
  harder to enable accidentally; explain LAN/Tailscale exposure at the point
  of configuration.

## 24. Knowledge graph and memory conflict review

- Add search/filter by entity and relationship, keyboard navigation, and clear
  source links; make graph meaning understandable to screen readers.
- Keep inferred relationships separate from database-backed relationships and
  label confidence/provenance if inference is later added.
- Improve conflict review to show source evidence, recency, and suggested
  resolution; allow keep-both, replace, dismiss, and undo.
- Bound graph queries and large-memory scans so the UI remains responsive.

## 25. Daily digest and notifications

- Let users choose digest time, timezone, source categories, and quiet hours;
  show why an item appeared and link to its source.
- Avoid duplicate notifications and support delivery history, retry status,
  per-event opt-in/out, and a test notification.
- Explain whether push content leaves the machine and provide a self-hosted
  ntfy option; redact sensitive content by default.
- Keep digest generation from silently creating memories or actions.

## 26. Automations and webhooks

- Add an automation dry-run/preview showing the trigger, data sent, action,
  target, and expected result before enabling.
- Add retry policy, delivery history, idempotency, deduplication, pause, and
  disable controls; cap repeated failures.
- Protect webhook URLs against SSRF and secret leakage; sign payloads and
  document event schema/versioning.
- Keep prompt automations bounded and non-agentic unless a separate explicit
  approval model is built; show the persistent conversation receiving output.

## 27. Tasks, notes, calendar, and email

- Improve tasks with due dates, priorities, project association, search, and
  reliable sync between list and board views; preserve keyboard operation.
- Improve notes with search, linking, export, and edit history.
- Make calendar timezone, recurrence, conflict, and provider state clear before
  creating events; add undo for edits where possible.
- Keep email actions review-first: show account, recipients, subject, and full
  body before send; add draft mode, retry, and no accidental send on automation.
- Provide connection test, credential rotation, and clear IMAP/SMTP error help.

## 28. Health, traces, usage, and diagnostics

- Turn health checks into actionable diagnostics with last checked time,
  latency, remediation steps, and component-specific retry.
- Add trace retention controls and redact prompts, file contents, keys, and
  personal data from traces by default.
- Make token/latency/provider usage data accurate where available and label
  estimates; offer per-model comparison and export.
- Add a downloadable diagnostic bundle with secrets and personal content
  excluded, plus a preview of exactly what will be included.
- Surface software version, database migration state, Ollama version, model
  inventory, and platform support status for useful bug reports.

## 29. Interface, accessibility, and onboarding

- Replace the first-run full tour as the default with a dismissible, optional
  “Get started” checklist. Let users reach chat immediately; keep the tour
  available from Help/Command Palette. Do not require account, persona, API key,
  agent, voice, or profile choices up front.
- Split installation into a clear recommended path per platform and a readiness
  check that reports missing prerequisites with copyable fixes. Allow setup to
  be skipped and resumed later.
- Explain local versus remote model choice, possible charges, data sharing, and
  permissions exactly when relevant. Never pre-enable remote routing, wake
  word, desktop control, or autonomous agent behavior.
- Complete a WCAG-oriented audit: keyboard navigation, focus restoration,
  screen-reader labels, contrast, reduced motion, zoom, and mobile touch sizes.
- Improve empty states, error copy, loading skeletons, settings search, and
  contextual help. Prefer progressive disclosure over presenting every feature
  at once.
- Make command palette and shortcuts consistent across OSes; provide visible
  alternatives for users who do not know keyboard shortcuts.

## 30. Public API, integrations, and extensions

- Publish a versioned OpenAPI description and examples for authentication,
  streaming, pagination, errors, and rate/size limits.
- Add stable API key creation/revocation and scope choices if external clients
  are supported; keep the current shared-secret mode understandable and safe.
- Provide small Python and TypeScript examples for common operations and an
  event/webhook schema reference.
- Add compatibility and smoke checks for the browser extension, mobile/PWA,
  desktop shell, and external MCP clients.
- For shareable feature packs, show contents, source, version, and requested
  permissions before import; support update and rollback.

## 31. Desktop, mobile, and distribution

- Make desktop packaging, updater, data directories, logs, and uninstall
  behavior consistent; explain where user data remains after uninstall.
- Hand-verify install, upgrade, rollback, sleep/resume, tray, hotkey, and
  accessibility behavior on each claimed platform.
- Improve mobile layouts and connection troubleshooting for LAN/Tailscale;
  clearly show whether the device can reach the backend and what the exposure
  settings mean.
- Publish prebuilt Docker images with pinned versions, health checks, persistent
  volume guidance, backup/upgrade instructions, and secure defaults.
- Add signed/notarized builds as credentials and release infrastructure allow;
  label unsigned or unverified builds plainly.

## 32. Continuous integration, documentation, and release quality

- Maintain layered checks: unit tests for services, API contract tests,
  frontend component tests, end-to-end happy paths, migration/import/export
  tests, and platform smoke checks.
- Add reliability tests for stream resume, cancellation, model/provider outage,
  corrupted attachments, database migration, and backup restore.
- Add retrieval, routing, multimodal, and agent evals using fixed fixtures;
  keep shell-driving agent evals opt-in and sandboxed.
- Track known limitations and supported platform/model matrices in one current
  place. Keep README, FEATURES, ROADMAP, onboarding, and UI copy aligned.
- Add structured logs with request/run identifiers, safe redaction, and useful
  user-facing error IDs; avoid swallowing failures silently.

## Cross-feature completion criteria

For each feature before calling it complete:

1. **Happy path:** the normal workflow succeeds on supported deployment types.
2. **Failure path:** bad configuration, unavailable service, timeout, cancel,
   and malformed data produce a clear and recoverable result.
3. **Data safety:** retries do not duplicate writes; destructive operations are
   previewed or recoverable; export/restore preserves user data.
4. **Privacy and permissions:** local/remote behavior and required access are
   visible before use; secrets and private content are not leaked to logs.
5. **Accessibility:** core actions work with keyboard, screen reader, zoom,
   and mobile touch where that surface is supported.
6. **Verification:** automated checks cover the contract and a real-user path
   is exercised on each platform claimed as supported.
7. **Documentation:** setup, limitations, troubleshooting, and current status
   match the shipped behavior.

## Suggested order

1. **Reliability foundation:** stream lifecycle, error handling, backup/restore,
   migrations, security review, and diagnostic quality.
2. **First-run experience:** installation readiness checks and optional,
   low-pressure onboarding.
3. **Model/provider clarity:** provider validation, capabilities, privacy and
   cost visibility, and explainable routing.
4. **Continuity and knowledge:** inspectable chat compaction, memory controls,
   source provenance, and retrieval quality.
5. **Agent work quality:** safer run review, sandbox/path checks, background
   runs, language diagnostics, and evaluation coverage.
6. **Multimodal depth:** improved image/OCR and timestamped video/audio analysis.
7. **Broader integrations and platform polish:** MCP, public API, task/email/
   calendar workflows, signed releases, and independent sync as a separate
   architecture project.

The sequence is a prioritization suggestion, not a promise that every item is
required. Ship additions when the current behavior is reliable, understandable,
and maintainable.
