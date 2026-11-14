# Zenith roadmap — backlog

Ideas parked for later, picked up one at a time when there's a reason to.
Effort: **S** ≈ an afternoon · **M** ≈ a day or two · **L** ≈ a week or more.

## Core — makes the main loop better

| # | Feature | Why | Effort |
|---|---|---|---|
| C3 | **LSP diagnostics after edits** | Type errors and bad imports come back to the agent right after an edit instead of after a full test run. | M–L |
| C4 | **Background tasks in git worktrees** | Queue a task, the agent works on an isolated branch, you review one diff. Builds on the task board and checkpoint/resume. | L |
| C6 | **Commit per agent change** | Optional: each approved edit becomes its own commit on a work branch, so git history is the undo log and a run is reviewable as one diff. | M |
| C7 | **Summarise long sessions** | Today the agent keeps the last 24 messages and drops the rest. Fold older turns into a running summary instead. | M |
| C8 | **Ranked repo map** | Rank files by relevance to the request (references, recently touched) instead of path order, so big repos get symbols for the files that matter. | M |
| C9 | **Bigger agent eval** | Five tasks is too few to compare models. Add multi-file, test-driven and git tasks. | M |

## Experience

Zenith stays chat-first: these make the code side panel pleasant, not an IDE.

| # | Feature | Why | Effort |
|---|---|---|---|
| E2 | **Inline edit** | Select code in the panel, ask, get a diff in place with the existing per-hunk accept/skip. Lighter than a full agent turn. | M |

## Platform & distribution

| # | Feature | Why | Effort |
|---|---|---|---|
| P1 | **Notarized macOS builds** | Needs an Apple Developer ID; removes the right-click → Open step. | S (+ account) |
| P2 | **Windows code signing** | SmartScreen warns on unsigned installers. | S (+ certificate) |
| P3 | **Encrypted sync between your machines** | Multi-master sync with conflict resolution; today devices share one backend. | L |
| P5 | **In-app accounts with permissions** | Today: separate profiles per person (`ZENITH_PROFILE`). Real roles inside one instance is a large change to every table. | L |
| P6 | **Any OpenAI-compatible local server** | llama.cpp, LM Studio and vLLM users can't use Zenith today; it only talks to Ollama. Biggest adoption gap. Parked 2026-11-13: do not start unprompted. | M–L |
| P7 | **Prebuilt Docker image** | Publish to GHCR from the release workflow so install is one `docker run`, not a build from source. Parked 2026-11-13. | S |
| P8 | **Shareable extensions beyond MCP** | Other front ends have community functions and pipelines. Smallest version: importable packs of quick actions, personas and automation rules. Parked 2026-11-13. | M |
| P9 | **Tested on more setups** | Hand-verified on one Linux laptop. A support matrix (OS, GPU, Ollama version) filled in from real reports, plus the Windows/macOS smoke runs. Parked 2026-11-13. | ongoing |

## Known follow-ups

- Agent evals on real local models (`cd backend && python -m evals agent --model <model> --repeat 3`) — run by hand; automated runs of a shell-driving agent are blocked by design.
- Two commits in the 0.10.0 history have messages that don't match their contents (content is correct; fixing needs a history rewrite).
