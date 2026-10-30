// Static data shared by SettingsPanel and its section components.

export const THEMES = [
  { id: "oled-ember", name: "OLED Ember", bg: "#000000", fg: "#ededed", accent: "#e8875c", font: "'Geist', sans-serif" },
  { id: "midnight-glass", name: "Midnight Glass", bg: "#12151f", fg: "#dde1ea", accent: "#4dd9c0", font: "'Space Grotesk', sans-serif" },
  { id: "terminal-noir", name: "Terminal Noir", bg: "#081008", fg: "#b8ffce", accent: "#58ff8a", font: "'JetBrains Mono', monospace" },
  { id: "command-center", name: "Command Center", bg: "#0b1319", fg: "#d6e4ec", accent: "#00d9ff", font: "'JetBrains Mono', monospace" },
  { id: "deep-space", name: "Deep Space", bg: "#0a0a16", fg: "#e8e6ff", accent: "#7b6cff", font: "'Space Grotesk', sans-serif" },
  { id: "brutalist-mono", name: "Brutalist Mono", bg: "#f2f2f0", fg: "#0a0a0a", accent: "#0a0a0a", font: "'IBM Plex Mono', monospace" },
  { id: "zen-minimal", name: "Zen Minimal", bg: "#ffffff", fg: "#1c1c1c", accent: "#1c1c1c", font: "'Inter', sans-serif" },
  { id: "cyber-grid", name: "Cyber Grid", bg: "#0e0a17", fg: "#f0e9ff", accent: "#00fff7", font: "'JetBrains Mono', monospace" },
  { id: "slate", name: "Slate", bg: "#17181c", fg: "#e4e5e8", accent: "#8f97a3", font: "'Inter', sans-serif" },
];

export const FIT_RANK = { comfortable: 0, tight: 1, unknown: 2, will_struggle: 3 };

/** Task filter chips for the "models" settings section — maps a friendly
 * label to the underlying COOKBOOK/CLOUD_COOKBOOK `role` value. */
export const MODEL_TASK_FILTERS = [
  { key: "all", label: "All" },
  { key: "general", label: "Chat" },
  { key: "code", label: "Code" },
  { key: "vision", label: "Vision" },
  { key: "reasoning", label: "Reasoning" },
  { key: "small_fast", label: "Quick replies" },
];

/** Best already-installed, role-matching model for this hardware: prefer
 * a better fit tier, then (within the same tier) the biggest model —
 * more capable is better as long as it still comfortably fits. Returns
 * null if nothing tagged for the role or no hardware report yet. */
export function recommendedModelForRole(role, models, hardware) {
  if (!hardware?.installed?.length) return null;
  const fitByName = Object.fromEntries(hardware.installed.map((m) => [m.name, m]));
  const candidates = models
    .filter((m) => m.roles?.includes(role))
    .map((m) => ({ name: m.name, ...fitByName[m.name] }))
    .filter((m) => m.fit);
  if (!candidates.length) return null;
  candidates.sort((a, b) => {
    const rankDiff = (FIT_RANK[a.fit] ?? 9) - (FIT_RANK[b.fit] ?? 9);
    if (rankDiff !== 0) return rankDiff;
    return (b.params_b || 0) - (a.params_b || 0);
  });
  return candidates[0];
}

// A curated starting point, not a live directory — the MCP ecosystem has
// no central registry, so this is deliberately a short, hand-picked list
// of well-known, keyless (no API account needed) servers that match
// Zenith's "free by construction" posture, not an attempt at completeness.
export const POPULAR_MCP_SERVERS = [
  {
    name: "filesystem", command: "npx", args: "-y @modelcontextprotocol/server-filesystem /path/to/allow",
    description: "Read/write access to a specific directory you choose — replace /path/to/allow before adding.",
  },
  {
    name: "fetch", command: "npx", args: "-y @modelcontextprotocol/server-fetch",
    description: "Fetch and read web pages as clean markdown/text.",
  },
  {
    name: "memory", command: "npx", args: "-y @modelcontextprotocol/server-memory",
    description: "A simple external knowledge-graph memory store, separate from Zenith's own memory.",
  },
  {
    name: "sequential-thinking", command: "npx", args: "-y @modelcontextprotocol/server-sequential-thinking",
    description: "Structured step-by-step reasoning scratchpad for harder problems.",
  },
  {
    name: "git", command: "uvx", args: "mcp-server-git",
    description: "Structured git operations via Python's uv — an alternative to Zenith's built-in git tool for a different repo.",
  },
];

export const ROLES = ["general", "code", "vision", "reasoning", "small_fast", "embedding"];
export const ROLE_LABEL = {
  general: "General chat",
  code: "Code",
  vision: "Vision (images/video)",
  reasoning: "Reasoning / math",
  small_fast: "Quick / small talk",
  embedding: "Embeddings",
};

export const SECTIONS = [
  { id: "appearance", label: "Appearance", icon: "sun" },
  { id: "accessibility", label: "Accessibility", icon: "check" },
  { id: "connection", label: "Connection", icon: "bolt" },
  { id: "memory", label: "Memory & persona", icon: "layers" },
  { id: "personas", label: "Personas", icon: "masks" },
  { id: "agent", label: "Agent tools", icon: "bot" },
  { id: "skills", label: "Skills", icon: "bolt" },
  { id: "email", label: "Email", icon: "at-sign" },
  { id: "sync", label: "Sync", icon: "share" },
  { id: "council", label: "Council", icon: "users" },
  { id: "routing", label: "Model routing", icon: "target" },
  { id: "models", label: "Installed models", icon: "grid" },
  { id: "voice", label: "Voice & audio", icon: "mic" },
  { id: "data", label: "Data", icon: "download" },
  { id: "folders", label: "Folders", icon: "folder" },
  { id: "schedules", label: "Schedules", icon: "clock" },
  { id: "automation", label: "Automation", icon: "wrench" },
  { id: "about", label: "About", icon: "info" },
];
