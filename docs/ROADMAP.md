# Zenith roadmap — backlog

Ideas parked for later, picked up one at a time when there's a reason to.
Effort: **S** ≈ an afternoon · **M** ≈ a day or two · **L** ≈ a week or more.

## Core — makes the main loop better

| # | Feature | Why | Effort |
|---|---|---|---|
| C1 | **Hunk-level diff approvals** | Accept the fix, reject the noise: approve or reject each hunk of an agent edit, with word-level highlights. | L |
| C8 | **Model-swap aware queueing** | On small GPUs, chat and embedding models evict each other; batch background embeddings and avoid swaps during a live reply. | M |

## Experience

| # | Feature | Why | Effort |
|---|---|---|---|
| E1 | **Hands-free voice mode** | Full-screen orb, live transcript, barge-in; wake word already exists. | M |
| E2 | **Projects as workspaces** | Each project with its own memory, documents, agent folder and default persona. | L |
| E4 | **Mobile companion pairing** | Scan a QR to pair a phone over Tailscale, with passcode set in the same flow. | M |

## Platform & distribution

| # | Feature | Why | Effort |
|---|---|---|---|
| P1 | **Notarized macOS builds** | Needs an Apple Developer ID; removes the right-click → Open step. | S (+ account) |
| P2 | **Windows code signing** | SmartScreen warns on unsigned installers. | S (+ certificate) |
| P3 | **Encrypted sync between your machines** | Multi-master sync with conflict resolution; today devices share one backend. | L |
| P4 | **Plugin / skill gallery** | Discover and install MCP servers and skills from inside the app. | L |
| P5 | **In-app accounts with permissions** | Today: separate profiles per person (`ZENITH_PROFILE`). Real roles inside one instance is a large change to every table. | L |

## Known follow-ups

- Agent evals on real local models (`cd backend && python -m evals agent --model <model> --repeat 3`) — run by hand; automated runs of a shell-driving agent are blocked by design.
- Two commits in the 0.10.0 history have messages that don't match their contents (content is correct; fixing needs a history rewrite).
