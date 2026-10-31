// Human-curated changelog — updated when a real feature ships, not
// generated from commits. Newest first.
export interface ChangelogEntry {
  version: string;
  date: string;
  title: string;
  items: string[];
}

export const CHANGELOG: ChangelogEntry[] = [
  {
    version: "0.11.0",
    date: "2026-10-31",
    title: "Terminal feel, voice orb, and smarter agent",
    items: [
      "Terminal look: dithered empty state, mono sidebar, route badges with a confidence meter, tool calls as a tree log.",
      "Hands-free voice mode: full-screen orb, stops when you stop talking, talk over a reply to interrupt.",
      "Approve or skip each change in an agent edit.",
      "MCP gallery: search the official registry and install servers in one click.",
      "Projects as workspaces with their own persona and instructions.",
      "Pair a phone with a QR code. Slash commands, memory Undo, j/k to move between chats.",
      "Faster startup and fixes: markdown renders immediately, voice no longer blocks other requests.",
    ],
  },
  {
    version: "0.10.1",
    date: "2026-10-30",
    title: "Desktop startup reliability",
    items: [
      "Fixed desktop backend connections on Linux, Windows, and macOS by using the sidecar's loopback address instead of the webview URL scheme.",
      "Desktop startup now retries backend connections until the sidecar is ready.",
    ],
  },
  {
    version: "0.10.0",
    date: "2026-10-30",
    title: "OLED Ember, live thinking, and a security pass",
    items: [
      "New OLED Ember theme (now the default): true black, one warm accent, light as hierarchy.",
      "Thinking models stream their reasoning live; everyday replies no longer wait for it.",
      "Replies finish instantly: memory and indexing now run after the answer, not before.",
      "Your chats never auto-route to Ollama Cloud models; routing picks the best model your GPU can run.",
      "Approve or deny agent steps with y / n, stop with Esc; a status line shows model, context and speed.",
      "Security: localhost-only by default, secrets never returned by the API, optional Docker sandbox for the agent.",
      "Document search runs on real vectors (it silently fell back to keywords before) — in the desktop app too.",
    ],
  },
  {
    version: "0.9",
    date: "2026-08-01",
    title: "Search, diagnostics, and finishing touches",
    items: [
      "Unified search now covers Notes, To-dos, Calendar, and Research reports, not just chats/docs/memories.",
      "Per-message model override — answer just this one with a specific model instead of the auto-router's pick.",
      "RAG citations — recalled-context answers show which stored chunk they came from.",
      "Pre-run checkpoints for agent mode — restore the whole workspace to how it was before a run, not just one file.",
      "Usage & diagnostics dashboard — token throughput, latency, and disk usage trends over time.",
      "Real inline image previews on attachments instead of a filename chip.",
    ],
  },
  {
    version: "0.8",
    date: "2026-07-31",
    title: "Eight themes, self-hosted fonts, ambient backgrounds",
    items: [
      "Replaced the light/dark + accent-color system with eight full re-skins (Midnight Glass, Terminal Noir, Command Center, Deep Space, Brutalist Mono, Zen Minimal, Cyber Grid, Slate).",
      "Fonts are self-hosted — no calls to Google Fonts or any CDN.",
      "Optional ambient background animations (stars, rain, snow, matrix, bokeh, aurora), off by default and restricted to themes they actually fit.",
    ],
  },
  {
    version: "0.7",
    date: "2026-07-31",
    title: "Productivity suite, group chat, and sync",
    items: [
      "Notes (Keep-style), a dedicated to-do list, and a local calendar.",
      "Multi-persona group chat — bind a conversation to 2+ personas that reply in turn and react to each other.",
      "Multi-device sync — password + a paired device secret exchanged only via a one-time pairing code, encrypted export/import.",
      "Email client — local IMAP/SMTP, AI summarize and draft-reply (always reviewed before sending), background urgent-message triage.",
      "Standalone research dashboard — deep research saves as a reopenable report with sources and follow-up Q&A.",
      "Self-evolving skills — the agent notices repeated tool sequences (and recoveries from failures) and saves them as reusable playbooks.",
      "Hardware-aware model manager — detects your CPU/RAM/GPU and scores which models will actually run well.",
    ],
  },
  {
    version: "0.6",
    date: "2026-07-30",
    title: "Agent mode, branching, and workspace features",
    items: [
      "Full agent mode: shell sessions, file edit/diff/revert, git, browser automation, sub-agents, plan-first mode, test/lint auto-check loop.",
      "Branch tree visualization, side-by-side regeneration diff, quick actions on selected text, live document editor.",
      "Projects — group conversations with a shared working directory and scoped memory.",
      "Continuous voice conversation mode, live tok/s status rail, desktop packaging (installable app, not just a browser tab).",
    ],
  },
];
