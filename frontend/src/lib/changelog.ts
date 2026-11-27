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
    version: "1.2.8",
    date: "2026-11-27",
    title: "Safer, clearer, and easier to fix",
    items: [
      "Schedules at a time of day in your timezone, with missed-run and failure tracking. Deep research shows its plan first, and PDF answers cite the page.",
      "A recovery code for your passcode, lock when idle, and sign out other devices. Backups are checked before restoring.",
      "Resolve memory contradictions with keep, merge or undo. Digests at a set time, and private-by-default phone pushes with a test button.",
      "Workspace code search, go to definition and a Problems tab. Coding chats cite path:line. API keys and docs for your own scripts.",
      "Health checks say how to fix things, every error has an ID, and a diagnostic bundle shows exactly what it contains.",
    ],
  },
  {
    version: "1.2.7",
    date: "2026-11-27",
    title: "Tasks that run while you're away, mail, and tidier knowledge",
    items: [
      "Mail sorts your inbox and drafts replies you review before sending; the calendar imports and exports .ics and warns about clashes.",
      "Research reports keep your notes and show which sources back each claim, and can check for updates.",
      "Queue agent tasks that keep running with the window closed, then review exactly what they changed and undo it if needed.",
      "Manage chats in bulk, rate answers, compare models side by side, and see every notification in one place with quiet hours.",
      "Share a redacted copy, import from more assistants, see how fresh each web source is, and clean up duplicate or stale knowledge with undo.",
    ],
  },
  {
    version: "1.2.5",
    date: "2026-11-26",
    title: "Memory you can see and shape",
    items: [
      "Long chats keep a conversation state — goals, decisions, constraints, files, next steps — linked to the messages they came from. Edit or pin it from the chat menu.",
      "A memory browser to search, edit, scope, merge, turn off and export what Zenith remembers. Unsure or private facts wait for your OK.",
      "Replies show which memories they used. Docker installs can pull prebuilt images.",
    ],
  },
  {
    version: "1.2.4",
    date: "2026-11-24",
    title: "Workflows: build with agents on a canvas",
    items: [
      "Open Workflows in the sidebar and drag Agent, Memory, Web search, Human review and Output nodes onto a grid, then connect them.",
      "Run it and watch each step light up, with a live trace and each node's output. Review nodes pause until you approve.",
      "Branches run at the same time, and a failed step only skips what depends on it. Workflows and run history are saved on your machine.",
    ],
  },
  {
    version: "1.2.3",
    date: "2026-11-22",
    title: "One look everywhere",
    items: [
      "Click the Zenith logo in the sidebar to go home: the sun rises and a new chat opens.",
      "Scrollbars are thin and only appear while you hover.",
      "The home screen shows the Zenith mark: the sun rises to its zenith, and glows while you type.",
      "Notes, To-do, Calendar, Research, the command palette and every other panel now match Settings and the home screen.",
    ],
  },
  {
    version: "1.2.1",
    date: "2026-11-21",
    title: "Smoother motion, a tidier Settings, and a working mic on Linux",
    items: [
      "Settings is grouped into General, Models, Agent, You, and Data & privacy, with a search box.",
      "Background animations are smooth on any screen, sharp on HiDPI, and match your theme colour.",
      "The microphone works in the Linux app again.",
    ],
  },
  {
    version: "1.2.0",
    date: "2026-11-21",
    title: "Desktop control, API providers and a Code view",
    items: [
      "Press Super+Space (Ctrl+Alt+Space elsewhere) and tell Zenith what to do on your desktop. It asks before every action; turn it on in Settings → Agent tools.",
      "Use OpenAI, Claude, Gemini, OpenRouter, Groq and more next to Ollama, from Settings → Providers.",
      "Code in the sidebar opens your project with files, an editor and a terminal beside the chat.",
      "A new home screen and message box, and a guided tour on first launch.",
      "Updates install from inside the app after you confirm; agent commands can run in a Bubblewrap sandbox.",
    ],
  },
  {
    version: "1.1.0",
    date: "2026-11-15",
    title: "A workspace beside the chat, git built in, and a model library",
    items: [
      "Open your project's files, a terminal and git changes beside the chat. Select code to ask about it or have it rewritten as a diff.",
      "Commit, branch, push and open pull requests from the Changes tab; hand a GitHub issue to the agent.",
      "Paste images with Ctrl+V. Browse and download models from the Ollama library in Settings.",
      "Your Ollama plan is shown, and cloud models it doesn't cover are skipped before you send anything.",
      "Dialogs and dropdowns now match your theme everywhere; the collapsed sidebar is a clean icon rail.",
    ],
  },
  {
    version: "1.0.1",
    date: "2026-11-14",
    title: "Pinned models that stop working no longer trap your chats",
    items: [
      "If Ollama refuses a pinned model (retired, or it needs paid credits), Zenith now picks a working model automatically and Settings → Model routing marks the pin as not working, with the reason.",
      "Saving a model choice shows an error if it fails instead of silently doing nothing.",
      "Agent mode uses Zenith's JSON tool protocol by default; a small model scored 8/10 with it versus 3/10 with Ollama's native tool calling.",
      "The README and the autonomy picker now say plainly what runs without asking, and that undo covers file edits, not commands.",
    ],
  },
  {
    version: "1.0.0",
    date: "2026-11-13",
    title: "First public release: the agent can search and map your code",
    items: [
      "Agent mode has grep and glob tools: it searches file contents and finds files by pattern without going through the shell.",
      "Repo map: with a working folder bound, the agent starts with an outline of your project's files and the functions and classes in them. Toggle in Settings → Agent tools.",
    ],
  },
  {
    version: "0.11.1",
    date: "2026-11-01",
    title: "A real folder picker, and the popovers people actually use",
    items: [
      "Browse for a working directory or watched folder instead of typing a path: breadcrumbs, quick locations, recent folders, or the OS's own dialog in the desktop app.",
      "Fixed the model picker growing past the window — it's now searchable, scrollable, and groups local models before Ollama Cloud ones.",
      "Fixed the header's \"More panels\" menu showing each icon above its label instead of beside it, and grouped its 13 actions.",
      "Every small popover in the app is now opaque against the OLED theme instead of reading as translucent.",
    ],
  },
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
