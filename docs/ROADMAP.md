# Zenith roadmap — backlog

Ideas parked for later, picked up one at a time when there's a reason to.
Effort: **S** ≈ an afternoon · **M** ≈ a day or two · **L** ≈ a week or more.

## Core — makes the main loop better

| # | Feature | Why | Effort |
|---|---|---|---|
| C3 | **LSP diagnostics after edits** | Type errors and bad imports come back to the agent right after an edit instead of after a full test run. | M–L |
| C4 | **Background tasks in git worktrees** | Queue a task, the agent works on an isolated branch, you review one diff. Builds on the task board and checkpoint/resume. | L |
| C5 | **GitHub issue → PR flow** | "Fix issue #12" becomes a branch, commits and a PR via `gh`. | M |

## Experience

Zenith stays chat-first: these make the code side panel pleasant, not an IDE.

| # | Feature | Why | Effort |
|---|---|---|---|
| E1 | **CodeMirror editor + terminal in the code panel** | Replaces the textarea-over-highlighter; xterm.js attaches to the existing persistent shell sessions. | M |
| E2 | **Inline edit** | Select code in the panel, ask, get a diff in place with the existing per-hunk accept/skip. Lighter than a full agent turn. | M |

## Platform & distribution

| # | Feature | Why | Effort |
|---|---|---|---|
| P1 | **Notarized macOS builds** | Needs an Apple Developer ID; removes the right-click → Open step. | S (+ account) |
| P2 | **Windows code signing** | SmartScreen warns on unsigned installers. | S (+ certificate) |
| P3 | **Encrypted sync between your machines** | Multi-master sync with conflict resolution; today devices share one backend. | L |
| P5 | **In-app accounts with permissions** | Today: separate profiles per person (`ZENITH_PROFILE`). Real roles inside one instance is a large change to every table. | L |

## Known follow-ups

- Agent evals on real local models (`cd backend && python -m evals agent --model <model> --repeat 3`) — run by hand; automated runs of a shell-driving agent are blocked by design.
- Two commits in the 0.10.0 history have messages that don't match their contents (content is correct; fixing needs a history rewrite).
