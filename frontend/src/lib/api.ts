// Resolve the desktop sidecar separately from browser access: a Tauri
// webview's URL identifies the frontend origin and is not a fetchable API URL.
// In browsers, an explicit HTTP(S) override wins, then the page's own host is
// used for LAN/Tailscale access, with IPv4 loopback as the final fallback.
const BACKEND_PORT = "8420";
function resolveBase(): string {
  const location = typeof window !== "undefined" ? window.location : undefined;
  const requested = new URLSearchParams(location?.search ?? "").get("backendPort");
  const requestedPort = requested ? Number(requested) : NaN;
  const port = Number.isInteger(requestedPort) && requestedPort > 0 && requestedPort <= 65535
    ? String(requestedPort)
    : BACKEND_PORT;

  // Tauri uses non-web URL schemes on macOS and a reserved tauri.localhost
  // origin on Linux/Windows. Those identify the UI, not a backend endpoint:
  // constructing fetch URLs from them produces WebKit's opaque
  // "The string did not match the expected pattern" error. The bundled
  // sidecar always binds to IPv4 loopback, so use that directly on every OS.
  const tauriRuntime = typeof window !== "undefined" && (
    "__TAURI_INTERNALS__" in window ||
    location?.protocol === "tauri:" ||
    location?.hostname === "tauri.localhost"
  );
  if (tauriRuntime) return `http://127.0.0.1:${port}`;

  const explicit = import.meta.env.VITE_API_BASE;
  if (explicit) {
    try {
      const url = new URL(explicit);
      if (url.protocol === "http:" || url.protocol === "https:") return explicit.replace(/\/$/, "");
    } catch {
      // Ignore malformed build-time overrides and use the page's HTTP(S) host.
    }
  }

  if (location?.hostname && (location.protocol === "http:" || location.protocol === "https:")) {
    // Build with URL so IPv6 hosts, ports and schemes are serialized safely.
    try {
      const url = new URL(location.origin || `${location.protocol}//${location.host || location.hostname}`);
      url.port = port;
      return url.origin;
    } catch {
      // Unusual location object: fall through to loopback.
    }
  }
  return `http://127.0.0.1:${BACKEND_PORT}`;
}
const BASE = resolveBase();
export const API_BASE = BASE;

function storageGet(storeName: "localStorage" | "sessionStorage", key: string): string | null {
  try {
    return (globalThis[storeName] as Storage | undefined)?.getItem(key) ?? null;
  } catch {
    return null; // private mode / blocked storage
  }
}

// Credentials sent on every request:
//  - the passcode-lock unlock token (issued by /api/lock/verify), kept in
//    sessionStorage so it clears when the tab closes;
//  - the optional deploy-time shared secret (auth_enabled), kept in
//    localStorage since it's per-device configuration, not a session.
export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = storageGet("sessionStorage", "zenith-unlock");
  if (token) headers["X-Zenith-Unlock"] = token;
  const secret = storageGet("localStorage", "zenith-secret");
  if (secret) headers.Authorization = `Bearer ${secret}`;
  return headers;
}

// The backend tags gate refusals with a `code` (see app/core/security.py);
// App.jsx listens for this and swaps in the matching access screen.
export const GATE_EVENT = "zenith:access-gate";
export type GateKind = "auth" | "remote";
const GATE_CODES: Record<string, GateKind> = { auth_required: "auth", remote_access_blocked: "remote" };

interface ErrorBody {
  detail?: unknown;
  code?: string;
}

function signalGate(body: ErrorBody | null | undefined): void {
  const kind = body?.code ? GATE_CODES[body.code] : undefined;
  if (kind && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(GATE_EVENT, { detail: { kind, message: body?.detail } }));
  }
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ErrorBody;
    signalGate(body);
    return typeof body.detail === "string" ? body.detail : res.statusText;
  } catch {
    return res.statusText; // non-JSON error body
  }
}

async function request(path: string, options: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res;
}

/** Reads one SSE response body, forwarding parsed frames to onEvent.
 * Returns "done" | "error" | "interrupted" (reader threw — the caller
 * decides whether that's resumable) | "clean-end" (stream closed with
 * no explicit done/error, e.g. an AbortError further up already handled). */
export type StreamEvent = { type: string; [key: string]: unknown };
export type StreamHandler = (event: StreamEvent) => void;
type StreamOutcome = "done" | "error" | "interrupted" | "clean-end";

async function consumeSSEBody(res: Response, onEvent: StreamHandler): Promise<StreamOutcome> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawTerminal: "done" | "error" | null = null;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        try {
          const ev = JSON.parse(line.slice(5).trim()) as StreamEvent;
          onEvent(ev);
          if (ev.type === "done" || ev.type === "error") sawTerminal = ev.type;
        } catch {
          /* ignore malformed chunk */
        }
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return "clean-end";
    return "interrupted";
  }
  return sawTerminal || "clean-end";
}

/**
 * A dropped connection (wifi blip, laptop sleep) used to lose the reply
 * entirely — the backend now keeps generating in the background
 * regardless (see stream_registry.py) and this reconnects to pick up
 * where the first connection left off, instead of surfacing a dead-end
 * error immediately.
 */
async function streamSSE(
  path: string, body: unknown, onEvent: StreamHandler, signal?: AbortSignal, resumePath: string | null = null,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    onEvent({ type: "error", message: `Network error: ${err instanceof Error ? err.message : String(err)}` });
    return;
  }
  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: await errorDetail(res) });
    return;
  }

  let outcome = await consumeSSEBody(res, onEvent);
  if (outcome !== "interrupted" || !resumePath || (signal && signal.aborted)) return;

  // Retry the reconnect itself a few times (the drop might still be in
  // progress — laptop still waking up, wifi still reassociating), not
  // just the read.
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await new Promise((r) => setTimeout(r, 600 * (attempt + 1)));
    if (signal && signal.aborted) return;
    let resumeRes: Response;
    try {
      resumeRes = await fetch(`${BASE}${resumePath}`, { headers: authHeaders(), signal });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      continue; // still down — try again
    }
    if (resumeRes.status === 404) {
      // Nothing left to resume (finished and aged out, or never
      // started) — give up cleanly instead of retrying forever.
      onEvent({ type: "error", message: "Connection dropped and the reply could not be recovered." });
      return;
    }
    if (!resumeRes.ok || !resumeRes.body) continue;
    outcome = await consumeSSEBody(resumeRes, onEvent);
    if (outcome !== "interrupted") return;
  }
  onEvent({ type: "error", message: "Connection dropped and could not be re-established." });
}

export interface ChatTurn {
  conversationId: string;
  message: string;
  attachmentIds: string[];
  webSearch?: boolean;
  agentMode?: boolean;
  deepResearch?: boolean;
  editOf?: string | null;
  regenerateOf?: string | null;
  modelOverride?: string | null;
}

export const api = {
  base: BASE,

  cleanupScan: () => request("/api/cleanup/scan").then((r) => r.json()),
  cleanupApply: (ids: string[]) =>
    request("/api/cleanup/apply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) }).then((r) => r.json()),
  cleanupUndo: (batchId: string) => request(`/api/cleanup/undo/${batchId}`, { method: "POST" }).then((r) => r.json()),
  listApiKeys: () => request("/api/api-keys").then((r) => r.json()),
  createApiKey: (name: string, scope: string) =>
    request("/api/api-keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, scope }) }).then((r) => r.json()),
  rotateApiKey: (id: string) => request(`/api/api-keys/${id}/rotate`, { method: "POST" }).then((r) => r.json()),
  revokeApiKey: (id: string) => request(`/api/api-keys/${id}`, { method: "DELETE" }),
  setupStatus: () => request("/api/setup/status").then((r) => r.json()),
  checkProvider: (body: Record<string, unknown>) =>
    request("/api/providers/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json()),
  renderTemplate: (template: string, values: Record<string, string>) =>
    request("/api/quick-actions/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template, values }),
    }).then((r) => r.json()),
  packExportUrl: (name = "My Zenith pack") => `${BASE}/api/packs/export?name=${encodeURIComponent(name)}`,
  previewPack: (pack: unknown) =>
    request("/api/packs/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pack }),
    }).then((r) => r.json()),
  importPack: (pack: unknown, include: string[] | null = null) =>
    request("/api/packs/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pack, include }),
    }).then((r) => r.json()),
  listNotifications: (params: { q?: string; event_type?: string; since?: number; unread?: boolean } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "" && v !== false).map(([k, v]) => [k, String(v)])).toString();
    return request(`/api/notifications${qs ? `?${qs}` : ""}`).then((r) => r.json());
  },
  markNotificationsRead: (ids: string[] | null = null) =>
    request("/api/notifications/read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    }),
  clearNotifications: () => request("/api/notifications", { method: "DELETE" }),
  setFeedback: (messageId: string, body: { rating?: number; wrong_model?: boolean; note?: string }) =>
    request(`/api/messages/${messageId}/feedback`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  conversationFeedback: (conversationId: string) =>
    request(`/api/conversations/${conversationId}/feedback`).then((r) => r.json()),
  feedbackSummary: () => request("/api/feedback/summary").then((r) => r.json()),
  runCompare: (body: { prompt: string; models: string[]; system?: string | null }, onEvent: StreamHandler, signal?: AbortSignal) =>
    streamSSE("/api/compare", body, onEvent, signal),
  listCompares: () => request("/api/compare").then((r) => r.json()),
  setCompareWinner: (id: string, model: string | null) =>
    request(`/api/compare/${id}/winner`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model }),
    }),
  deleteCompare: (id: string) => request(`/api/compare/${id}`, { method: "DELETE" }),
  bulkConversations: (ids: string[], action: string, tag: string | null = null) =>
    request("/api/conversations/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, action, tag }),
    }).then((r) => r.json()),
  queueBackgroundRun: (conversationId: string, prompt: string, model: string | null = null) =>
    request("/api/agent/background", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId, prompt, model }),
    }).then((r) => r.json()),
  listBackgroundRuns: (params: { conversation_id?: string; since?: number } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "").map(([k, v]) => [k, String(v)])).toString();
    return request(`/api/agent/background${qs ? `?${qs}` : ""}`).then((r) => r.json());
  },
  getBackgroundRun: (id: string) => request(`/api/agent/background/${id}`).then((r) => r.json()),
  cancelBackgroundRun: (id: string) => request(`/api/agent/background/${id}/cancel`, { method: "POST" }),
  markBackgroundReviewed: (id: string) => request(`/api/agent/background/${id}/reviewed`, { method: "POST" }),
  reviewRun: (runId: string) => request(`/api/agent/runs/${runId}/review`).then((r) => r.json()),

  getConversationState: (id: string) => request(`/api/conversations/${id}/state`).then((r) => r.json()),
  saveConversationState: (id: string, state: unknown) =>
    request(`/api/conversations/${id}/state`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state }),
    }).then((r) => r.json()),
  regenerateConversationState: (id: string) =>
    request(`/api/conversations/${id}/state/regenerate`, { method: "POST" }).then((r) => r.json()),
  clearConversationState: (id: string) => request(`/api/conversations/${id}/state`, { method: "DELETE" }),

  listWorkflows: () => request("/api/workflows").then((r) => r.json()),
  saveWorkflow: (body: { id?: string | null; name: string; graph: unknown }) =>
    request("/api/workflows", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json()),
  deleteWorkflow: (id: string) => request(`/api/workflows/${id}`, { method: "DELETE" }),
  workflowRuns: (id: string) => request(`/api/workflows/${id}/runs`).then((r) => r.json()),
  runWorkflow: (
    body: { graph: unknown; input: string; workflow_id?: string | null },
    onEvent: StreamHandler,
    signal?: AbortSignal,
  ) => streamSSE("/api/workflows/run", body, onEvent, signal),
  reviewWorkflow: (runId: string, nodeId: string, approve: boolean) =>
    request(`/api/workflows/runs/${runId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ node_id: nodeId, approve }),
    }),

  listConversations: () => request("/api/conversations").then((r) => r.json()),
  createConversation: (title: string = "New chat", projectId: string | null = null) =>
    request("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, project_id: projectId }),
    }).then((r) => r.json()),
  renameConversation: (id: string, title: string) =>
    request(`/api/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id: string) => request(`/api/conversations/${id}`, { method: "DELETE" }),
  getMessages: (id: string) => request(`/api/conversations/${id}/messages`).then((r) => r.json()),
  setTitle: (id: string, title: string) =>
    request(`/api/conversations/${id}/title`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).then((r) => r.json()),
  searchConversations: (query: string) =>
    request(`/api/conversations/search?q=${encodeURIComponent(query)}`).then((r) => r.json()),
  searchAll: (query: string) =>
    request(`/api/search/all?q=${encodeURIComponent(query)}`).then((r) => r.json()),

  listPersonas: () => request("/api/personas").then((r) => r.json()),
  createPersona: (name: string, systemPrompt: string, icon: string | null = null) =>
    request("/api/personas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, system_prompt: systemPrompt, icon }),
    }).then((r) => r.json()),
  updatePersona: (id: string, patch: Record<string, unknown>) =>
    request(`/api/personas/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  deletePersona: (id: string) => request(`/api/personas/${id}`, { method: "DELETE" }),
  setConversationPersona: (conversationId: string, personaId: string) =>
    request(`/api/conversations/${conversationId}/persona`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona_id: personaId }),
    }),
  setConversationWorkdir: (conversationId: string, workdir: string | null) =>
    request(`/api/conversations/${conversationId}/workdir`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workdir }),
    }).then((r) => r.json()),

  exportUrl: (format: string) => `${BASE}/api/export/${format}`,
  conversationPdfUrl: (conversationId: string) => `${BASE}/api/export/${conversationId}/pdf`,

  // Full backup (DB + config.json + attachments), distinct from the data-only
  // export above. See app/api/backup.py — not yet registered in main.py.
  backupUrl: () => `${BASE}/api/backup/create`,
  restoreBackup: (file: File, confirm: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("confirm", confirm ? "true" : "false");
    return request("/api/backup/restore", { method: "POST", body: form }).then((r) => r.json());
  },

  inlineEdit: (cid: string, req: { path: string; content: string; from_line: number; to_line: number; instruction: string }):
    Promise<{ model: string; original: string; replacement: string }> =>
    request(`/api/conversations/${cid}/inline-edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }).then((r) => r.json()),
  gitWorktrees: (cid: string): Promise<{ worktrees: { path: string; branch?: string }[] }> =>
    request(`/api/conversations/${cid}/git/worktrees`).then((r) => r.json()),
  gitNewWorktree: (cid: string, name: string): Promise<{ path: string; branch: string; conversation_id: string }> =>
    request(`/api/conversations/${cid}/git/worktrees`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then((r) => r.json()),
  gitRemoveWorktree: (cid: string, path: string) =>
    request(`/api/conversations/${cid}/git/worktrees/remove`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }).then((r) => r.json()),
  gitState: (cid: string) => request(`/api/conversations/${cid}/git`).then((r) => r.json()),
  gitFileDiff: (cid: string, path: string, staged = false) =>
    request(`/api/conversations/${cid}/git/file-diff?path=${encodeURIComponent(path)}&staged=${staged}`).then((r) => r.json()),
  gitLog: (cid: string, count = 20) => request(`/api/conversations/${cid}/git/log?count=${count}`).then((r) => r.json()),
  gitBranches: (cid: string) => request(`/api/conversations/${cid}/git/branches`).then((r) => r.json()),
  gitStage: (cid: string, paths: string[]) => request(`/api/conversations/${cid}/git/stage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    }).then((r) => r.json()),
  gitUnstage: (cid: string, paths: string[]) => request(`/api/conversations/${cid}/git/unstage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    }).then((r) => r.json()),
  gitCommit: (cid: string, message: string) => request(`/api/conversations/${cid}/git/commit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }).then((r) => r.json()),
  gitSwitch: (cid: string, name: string, create = false) => request(`/api/conversations/${cid}/git/switch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, create }),
    }).then((r) => r.json()),
  gitPush: (cid: string) => request(`/api/conversations/${cid}/git/push`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }).then((r) => r.json()),
  githubState: (cid: string) => request(`/api/conversations/${cid}/github`).then((r) => r.json()),
  githubIssues: (cid: string) => request(`/api/conversations/${cid}/github/issues`).then((r) => r.json()),
  githubIssue: (cid: string, n: number) => request(`/api/conversations/${cid}/github/issues/${n}`).then((r) => r.json()),
  githubPulls: (cid: string) => request(`/api/conversations/${cid}/github/pulls`).then((r) => r.json()),
  githubCreatePull: (cid: string, pr: { title: string; body: string; base?: string; draft?: boolean }) =>
    request(`/api/conversations/${cid}/github/pulls`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pr),
    }).then((r) => r.json()),
  terminalAvailable: (): Promise<{ available: boolean }> =>
    request("/api/terminal/available").then((r) => r.json()),
  terminalStart: (conversationId: string, cols: number, rows: number): Promise<{ session_id: string; cwd: string; alive: boolean }> =>
    request(`/api/conversations/${conversationId}/terminal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cols, rows }),
    }).then((r) => r.json()),
  terminalOutput: (sid: string, since: number, wait = 20, signal?: AbortSignal): Promise<{ data: string; next: number; alive: boolean; exit_code: number | null }> =>
    request(`/api/terminal/${sid}/output?since=${since}&wait=${wait}`, { signal }).then((r) => r.json()),
  terminalInput: (sid: string, data: string) =>
    request(`/api/terminal/${sid}/input`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
    }).then((r) => r.json()),
  terminalResize: (sid: string, cols: number, rows: number) =>
    request(`/api/terminal/${sid}/resize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cols, rows }),
    }).then((r) => r.json()),
  terminalClose: (sid: string) => request(`/api/terminal/${sid}`, { method: "DELETE" }).then((r) => r.json()),
  codeSymbols: (conversationId: string, q: string) =>
    request(`/api/conversations/${conversationId}/code/symbols?q=${encodeURIComponent(q)}`).then((r) => r.json()),
  codeDefinition: (conversationId: string, name: string) =>
    request(`/api/conversations/${conversationId}/code/definition?name=${encodeURIComponent(name)}`).then((r) => r.json()),
  codeReferences: (conversationId: string, name: string) =>
    request(`/api/conversations/${conversationId}/code/references?name=${encodeURIComponent(name)}`).then((r) => r.json()),
  codeCheck: (conversationId: string) =>
    request(`/api/conversations/${conversationId}/code/check`, { method: "POST" }).then((r) => r.json()),
  listWorkspaceFiles: (conversationId: string, path: string = "") =>
    request(`/api/conversations/${conversationId}/files?path=${encodeURIComponent(path)}`).then((r) => r.json()),
  readWorkspaceFile: (conversationId: string, path: string) =>
    request(`/api/conversations/${conversationId}/files/content?path=${encodeURIComponent(path)}`).then((r) => r.json()),
  writeWorkspaceFile: (conversationId: string, path: string, content: string) =>
    request(`/api/conversations/${conversationId}/files/content?path=${encodeURIComponent(path)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }).then((r) => r.json()),

  editDocument: (attachmentId: string, instruction: string) =>
    request(`/api/documents/${attachmentId}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    }).then((r) => r.json()),
  attachmentDownloadUrl: (attachmentId: string) => `${BASE}/api/attachments/${attachmentId}/download`,

  listFolders: () => request("/api/folders").then((r) => r.json()),
  addFolder: (path: string, extensions: string[] | null = null) =>
    request("/api/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, extensions }),
    }).then((r) => r.json()),
  toggleFolder: (id: string, enabled: boolean) =>
    request(`/api/folders/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  removeFolder: (id: string) => request(`/api/folders/${id}`, { method: "DELETE" }),
  scanFolderNow: (id: string) => request(`/api/folders/${id}/scan`, { method: "POST" }).then((r) => r.json()),

  listSchedules: () => request("/api/schedules").then((r) => r.json()),
  createSchedule: (name: string, prompt: string, mode: string, intervalMinutes: number, todoMode = "none") =>
    request("/api/schedules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, prompt, mode, interval_minutes: intervalMinutes, todo_mode: todoMode }),
    }).then((r) => r.json()),
  toggleSchedule: (id: string, enabled: boolean) =>
    request(`/api/schedules/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  deleteSchedule: (id: string) => request(`/api/schedules/${id}`, { method: "DELETE" }),
  listScheduleRuns: (id: string) => request(`/api/schedules/${id}/runs`).then((r) => r.json()),
  recentScheduleRuns: (since: number) => request(`/api/schedules/recent-runs?since=${since}`).then((r) => r.json()),
  runScheduleNow: (id: string) => request(`/api/schedules/${id}/run-now`, { method: "POST" }).then((r) => r.json()),

  listMcpServers: () => request("/api/mcp/servers").then((r) => r.json()),
  searchMcpRegistry: (q: string) => request(`/api/mcp/registry?q=${encodeURIComponent(q)}`).then((r) => r.json()),
  addMcpServer: (name: string, command: string, args: string[] = [], env: Record<string, string> = {}) =>
    request("/api/mcp/servers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, command, args, env }),
    }).then((r) => r.json()),
  toggleMcpServer: (id: string, enabled: boolean) =>
    request(`/api/mcp/servers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  removeMcpServer: (id: string) => request(`/api/mcp/servers/${id}`, { method: "DELETE" }),
  getMcpServerTools: (id: string) => request(`/api/mcp/servers/${id}/tools`).then((r) => r.json()),

  listBranches: (conversationId: string) =>
    request(`/api/conversations/${conversationId}/branches`).then((r) => r.json()),
  activateBranch: (conversationId: string, messageId: string) =>
    request(`/api/conversations/${conversationId}/messages/${messageId}/activate`, {
      method: "POST",
    }).then((r) => r.json()),
  deleteMessage: (conversationId: string, messageId: string) =>
    request(`/api/conversations/${conversationId}/messages/${messageId}`, {
      method: "DELETE",
    }).then((r) => r.json()),

  hardwareReport: () => request("/api/hardware").then((r) => r.json()),
  modelLibrary: (q = "", category = "") =>
    request(`/api/models/library?q=${encodeURIComponent(q)}&category=${encodeURIComponent(category)}`).then((r) => r.json()),
  modelLibraryTags: (name: string) => request(`/api/models/library/${encodeURIComponent(name)}`).then((r) => r.json()),
  checkModel: (name: string) =>
    request("/api/models/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).then((r) => r.json()),
  ollamaAccount: () => request("/api/ollama/account").then((r) => r.json()),
  desktopStatus: () => request("/api/desktop/status").then((r) => r.json()),
  setDesktopAccessibility: (enabled: boolean) =>
    request("/api/desktop/accessibility", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }).then((r) => r.json()),
  hideQuickbar: () => request("/api/desktop/quickbar/hide", { method: "POST" }).then((r) => r.json()),
  listProviders: () => request("/api/providers").then((r) => r.json()),
  providerUsage: () => request("/api/providers/usage").then((r) => r.json()),
  providerPresets: () => request("/api/providers/presets").then((r) => r.json()),
  saveProvider: (p: Record<string, unknown>) =>
    request("/api/providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }).then((r) => r.json()),
  deleteProvider: (id: string) => request(`/api/providers/${encodeURIComponent(id)}`, { method: "DELETE" }).then((r) => r.json()),
  testProvider: (id: string) =>
    request(`/api/providers/${encodeURIComponent(id)}/test`, { method: "POST" }).then((r) => r.json()),
  listRagSources: () => request("/api/rag/sources").then((r) => r.json()),
  listTraces: (conversationId: string | null = null, limit: number = 50) =>
    request(`/api/traces?limit=${limit}${conversationId ? `&conversation_id=${encodeURIComponent(conversationId)}` : ""}`).then((r) => r.json()),
  webSearchTest: () => request("/api/web/search-test", { method: "POST" }).then((r) => r.json()),
  ragStatus: () => request("/api/rag/status").then((r) => r.json()),
  ragReindex: () => request("/api/rag/reindex", { method: "POST" }).then((r) => r.json()),
  deleteRagSource: (sourceId: string, sourceKind: string) =>
    request(`/api/rag/sources/${encodeURIComponent(sourceId)}?source_kind=${encodeURIComponent(sourceKind)}`, {
      method: "DELETE",
    }).then((r) => r.json()),
  usageSummary: (days: number = 14) => request(`/api/usage/summary?days=${days}`).then((r) => r.json()),
  usageStats: (days: number = 14) => request(`/api/usage/stats?days=${days}`).then((r) => r.json()),

  emailTest: () => request("/api/email/test").then((r) => r.json()),
  emailInbox: () => request("/api/email/inbox").then((r) => r.json()),
  emailTriage: (force = false) => request(`/api/email/triage?force=${force}`, { method: "POST" }).then((r) => r.json()),
  emailFilters: () => request("/api/email/filters").then((r) => r.json()),
  addEmailFilter: (f: { name: string; field: string; contains: string; category: string }) =>
    request("/api/email/filters", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) }).then((r) => r.json()),
  deleteEmailFilter: (id: string) => request(`/api/email/filters/${id}`, { method: "DELETE" }),
  emailDrafts: () => request("/api/email/drafts").then((r) => r.json()),
  createEmailDraft: (messageId: string, instruction = "") =>
    request(`/api/email/messages/${messageId}/draft`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ instruction }) }).then((r) => r.json()),
  updateEmailDraft: (id: string, patch: { to?: string; subject?: string; body?: string }) =>
    request(`/api/email/drafts/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) }).then((r) => r.json()),
  sendEmailDraft: (id: string) => request(`/api/email/drafts/${id}/send`, { method: "POST" }).then((r) => r.json()),
  discardEmailDraft: (id: string) => request(`/api/email/drafts/${id}`, { method: "DELETE" }),
  emailFlags: () => request("/api/email/flags").then((r) => r.json()),
  markEmailFlagsSeen: () => request("/api/email/flags/mark-seen", { method: "POST" }),
  emailMessages: () => request("/api/email/messages").then((r) => r.json()),
  emailMessage: (id: string) => request(`/api/email/messages/${id}`).then((r) => r.json()),
  emailSummarize: (id: string) =>
    request(`/api/email/messages/${id}/summarize`, { method: "POST" }).then((r) => r.json()),
  emailDraftReply: (id: string, instruction: string = "") =>
    request(`/api/email/messages/${id}/draft-reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    }).then((r) => r.json()),
  emailSend: (to: string, subject: string, body: string, inReplyTo: string | null = null) =>
    request("/api/email/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to, subject, body, in_reply_to: inReplyTo }),
    }).then((r) => r.json()),

  syncPairStart: () => request("/api/sync/pair/start", { method: "POST" }).then((r) => r.json()),
  syncPairBundle: (baseUrl: string, code: string) =>
    fetch(`${baseUrl}/api/sync/pair/bundle?code=${encodeURIComponent(code)}`).then((r) => {
      if (!r.ok) throw new Error("Invalid, expired, or already-used code.");
      return r.json();
    }),
  syncPairComplete: (code: string, encryptedSecret: string) =>
    request("/api/sync/pair/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, encrypted_secret: encryptedSecret }),
    }).then((r) => r.json()),
  syncExport: (passphrase: string) =>
    request("/api/sync/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase }),
    }).then((r) => r.json()),
  syncImport: (passphrase: string, blob: Blob | string) =>
    request("/api/sync/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase, blob }),
    }).then((r) => r.json()),

  getGroupPersonas: (conversationId: string) =>
    request(`/api/conversations/${conversationId}/group-personas`).then((r) => r.json()),
  setGroupPersonas: (conversationId: string, personaIds: string[]) =>
    request(`/api/conversations/${conversationId}/group-personas`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona_ids: personaIds }),
    }).then((r) => r.json()),
  streamGroupChat: (conversationId: string, message: string, onEvent: StreamHandler, signal: AbortSignal) =>
    streamSSE(`/api/conversations/${conversationId}/group-chat`, { message }, onEvent, signal),

  listResearchReports: () => request("/api/research/reports").then((r) => r.json()),
  getResearchReport: (id: string) => request(`/api/research/reports/${id}`).then((r) => r.json()),
  deleteResearchReport: (id: string) => request(`/api/research/reports/${id}`, { method: "DELETE" }),
  saveResearchNotes: (id: string, notes: string) =>
    request(`/api/research/reports/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ notes }) }).then((r) => r.json()),
  researchClaims: (id: string, force = false) =>
    request(`/api/research/reports/${id}/claims?force=${force}`, { method: "POST" }).then((r) => r.json()),
  researchVersions: (id: string) => request(`/api/research/reports/${id}/versions`).then((r) => r.json()),
  researchRerun: (id: string) => request(`/api/research/reports/${id}/rerun`, { method: "POST" }).then((r) => r.json()),
  researchRerunStatus: (id: string) => request(`/api/research/reports/${id}/rerun`).then((r) => r.json()),
  askResearchReport: (id: string, question: string) =>
    request(`/api/research/reports/${id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }).then((r) => r.json()),

  listTodos: () => request("/api/todos").then((r) => r.json()),
  createTodo: (text: string, dueTs: number | null = null) =>
    request("/api/todos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, due_ts: dueTs }),
    }).then((r) => r.json()),
  updateTodo: (id: string, patch: Record<string, unknown>) =>
    request(`/api/todos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),
  deleteTodo: (id: string) => request(`/api/todos/${id}`, { method: "DELETE" }),

  listNotes: () => request("/api/notes").then((r) => r.json()),
  createNote: (content: string, color: string = "default") =>
    request("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, color }),
    }).then((r) => r.json()),
  updateNote: (id: string, patch: Record<string, unknown>) =>
    request(`/api/notes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),
  deleteNote: (id: string) => request(`/api/notes/${id}`, { method: "DELETE" }),

  listCalendarEvents: (fromTs: number, toTs: number) =>
    request(`/api/calendar/events?from_ts=${fromTs}&to_ts=${toTs}`).then((r) => r.json()),
  createCalendarEvent: (event: Record<string, unknown>) =>
    request("/api/calendar/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    }).then((r) => r.json()),
  deleteCalendarEvent: (id: string) => request(`/api/calendar/events/${id}`, { method: "DELETE" }),
  /** Like createCalendarEvent, but a clash comes back as {conflicts} instead of throwing. */
  tryCreateCalendarEvent: async (event: Record<string, unknown>) => {
    const res = await fetch(`${BASE}/api/calendar/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(event),
    });
    if (res.status === 409) return { conflicts: (await res.json()).conflicts as unknown[] };
    if (!res.ok) throw new Error(await errorDetail(res));
    return { event: await res.json() };
  },
  importCalendar: (body: { ics?: string; url?: string }) =>
    request("/api/calendar/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json()),
  calendarExportUrl: () => `${BASE}/api/calendar/export.ics`,

  listProjects: () => request("/api/projects").then((r) => r.json()),
  createProject: (name: string, workdir: string) =>
    request("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, workdir }),
    }).then((r) => r.json()),
  updateProject: (id: string, fields: Record<string, string>) =>
    request(`/api/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    }).then((r) => r.json()),
  deleteProject: (id: string) => request(`/api/projects/${id}`, { method: "DELETE" }),
  setConversationProject: (conversationId: string, projectId: string) =>
    request(`/api/conversations/${conversationId}/project`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId }),
    }).then((r) => r.json()),
  setProjectAgentMode: (projectId: string, agentMode: string) =>
    request(`/api/projects/${projectId}/agent-mode`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_mode: agentMode }),
    }).then((r) => r.json()),

  setConversationPinned: (conversationId: string, pinned: boolean) =>
    request(`/api/conversations/${conversationId}/pin`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned }),
    }).then((r) => r.json()),
  setConversationTags: (conversationId: string, tags: string[]) =>
    request(`/api/conversations/${conversationId}/tags`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags }),
    }).then((r) => r.json()),

  sharePreview: (conversationId: string) => request(`/api/conversations/${conversationId}/share/preview`).then((r) => r.json()),
  shareSnapshot: (conversationId: string, body: { redact: unknown[]; exclude_message_ids: string[]; include_attachments: boolean }) =>
    request(`/api/conversations/${conversationId}/share`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  shareExport: (conversationId: string, body: { redact: unknown[]; exclude_message_ids: string[]; include_attachments: boolean }, format = "markdown") =>
    request(`/api/conversations/${conversationId}/share/export?format=${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.blob()),
  shareConversation: (conversationId: string) =>
    request(`/api/conversations/${conversationId}/share`, { method: "POST" }).then((r) => r.json()),
  unshareConversation: (conversationId: string) =>
    request(`/api/conversations/${conversationId}/share`, { method: "DELETE" }).then((r) => r.json()),
  getSharedConversation: (token: string) =>
    fetch(`${BASE}/api/share/${token}`).then((r) => {
      if (!r.ok) throw new Error("This link is invalid or has been revoked.");
      return r.json();
    }),
  shareUrl: (token: string) => `${window.location.origin}${window.location.pathname}#/share/${token}`,
  getKnowledgeGraph: () => request("/api/graph").then((r) => r.json()),
  searchLocalFiles: (path: string, q: string) =>
    request(`/api/search/local-files?path=${encodeURIComponent(path)}&q=${encodeURIComponent(q)}`).then((r) => r.json()),
  listDirectories: (path?: string) => {
    const q = path ? `?path=${encodeURIComponent(path)}` : "";
    return request(`/api/directories${q}`).then((r) => r.json());
  },
  getAutomationEventTypes: () => request("/api/automation/event-types").then((r) => r.json()),
  listWebhooks: () => request("/api/webhooks").then((r) => r.json()),
  createWebhook: (url: string, eventTypes: string[]) =>
    request("/api/webhooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, event_types: eventTypes }),
    }).then((r) => r.json()),
  toggleWebhook: (id: string, enabled: boolean) =>
    request(`/api/webhooks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  deleteWebhook: (id: string) => request(`/api/webhooks/${id}`, { method: "DELETE" }),
  listAutomationRules: () => request("/api/automation/rules").then((r) => r.json()),
  createAutomationRule: (rule: Record<string, unknown>) =>
    request("/api/automation/rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rule),
    }).then((r) => r.json()),
  toggleAutomationRule: (id: string, enabled: boolean) =>
    request(`/api/automation/rules/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  deleteAutomationRule: (id: string) => request(`/api/automation/rules/${id}`, { method: "DELETE" }),
  getLatestDigest: () => request("/api/digest/latest").then((r) => r.json()),
  getDigestHistory: () => request("/api/digest/history").then((r) => r.json()),
  runDigestNow: () => request("/api/digest/run-now", { method: "POST" }).then((r) => r.json()),
  extractProject: (conversationId: string) =>
    request(`/api/conversations/${conversationId}/extract-project`, { method: "POST" }).then((r) => r.json()),

  listSnippets: () => request("/api/snippets").then((r) => r.json()),
  createSnippet: (title: string, content: string) =>
    request("/api/snippets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content }),
    }).then((r) => r.json()),
  deleteSnippet: (id: string) => request(`/api/snippets/${id}`, { method: "DELETE" }),

  listQuickActions: () => request("/api/quick-actions").then((r) => r.json()),
  createQuickAction: (name: string, promptTemplate: string, autoSend: boolean) =>
    request("/api/quick-actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, prompt_template: promptTemplate, auto_send: autoSend }),
    }).then((r) => r.json()),
  deleteQuickAction: (id: string) => request(`/api/quick-actions/${id}`, { method: "DELETE" }),

  gitStatus: (conversationId: string) =>
    request(`/api/conversations/${conversationId}/git/status`).then((r) => r.json()),
  gitDiff: (conversationId: string, path: string = "") =>
    request(`/api/conversations/${conversationId}/git/diff?path=${encodeURIComponent(path)}`).then((r) => r.json()),
  runChecks: (conversationId: string, command: string | null = null) =>
    request(`/api/conversations/${conversationId}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(command ? { command } : {}),
    }).then((r) => r.json()),

  listSkills: () => request("/api/skills").then((r) => r.json()),
  deleteSkill: (id: string) => request(`/api/skills/${id}`, { method: "DELETE" }),

  listMemories: (since: number | null = null) =>
    request(`/api/memories${since ? `?since=${since}` : ""}`).then((r) => r.json()),
  addMemory: (content: string, category: string = "fact") =>
    request("/api/memories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, category }),
    }).then((r) => r.json()),
  toggleMemory: (id: string, enabled: boolean) =>
    request(`/api/memories/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  deleteMemory: (id: string) => request(`/api/memories/${id}`, { method: "DELETE" }),
  browseMemories: (params: { q?: string; scope?: string; status?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString();
    return request(`/api/memories/browse${qs ? `?${qs}` : ""}`).then((r) => r.json());
  },
  updateMemory: (id: string, patch: Record<string, unknown>) =>
    request(`/api/memories/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),
  mergeMemories: (ids: string[], content: string) =>
    request("/api/memories/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, content }),
    }).then((r) => r.json()),
  exportMemoriesUrl: () => `${BASE}/api/memories/export`,
  clearMemories: () => request("/api/memories", { method: "DELETE" }),
  reviewMemoryConflicts: () => request("/api/memories/review-conflicts", { method: "POST" }).then((r) => r.json()),
  listMemoryConflicts: () => request("/api/memories/conflicts").then((r) => r.json()),
  resolveMemoryConflict: (id: string) => request(`/api/memories/conflicts/${id}/resolve`, { method: "POST" }),

  approveToolCall: (id: string, rejectedHunks: number[] | null = null) =>
    request(`/api/agent/tool-calls/${id}/approve`, {
      method: "POST",
      ...(rejectedHunks?.length
        ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rejected_hunks: rejectedHunks }) }
        : {}),
    }),
  denyToolCall: (id: string) => request(`/api/agent/tool-calls/${id}/deny`, { method: "POST" }),
  revertToolCall: (id: string) =>
    request(`/api/agent/tool-calls/${id}/revert`, { method: "POST" }).then((r) => r.json()),
  listToolCalls: (conversationId: string) =>
    request(`/api/agent/tool-calls?conversation_id=${encodeURIComponent(conversationId)}`).then((r) => r.json()),
  revertRun: (runId: string) => request(`/api/agent/runs/${runId}/revert`, { method: "POST" }).then((r) => r.json()),

  // fresh=true skips the browser's short cache (after adding a provider or pulling a model).
  listModels: (fresh = false) => request("/api/models", fresh ? { cache: "no-store" } : {}).then((r) => r.json()),
  getPairing: () => request("/api/pairing").then((r) => r.json()),
  // Settings change history — see settings_history_service.py.
  getSettingsHistory: (key: string | null = null, limit: number = 100) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (key) params.set("key", key);
    return request(`/api/settings/history?${params.toString()}`).then((r) => r.json());
  },
  revertSettingsHistory: (id: string) =>
    request(`/api/settings/history/${id}/revert`, { method: "POST" }).then((r) => r.json()),
  getRoutingStatus: () => request("/api/routing/status").then((r) => r.json()),
  getUnavailableModels: (): Promise<Record<string, { status: number; reason: string }>> =>
    request("/api/models/unavailable").then((r) => r.json()),
  getRoutingOverrideSummary: (days: number = 30) =>
    request(`/api/routing/override-summary?days=${days}`).then((r) => r.json()),
  pullModel: (name: string, onEvent: StreamHandler) => streamSSE("/api/models/pull", { name }, onEvent),
  createModel: (spec: Record<string, unknown>, onEvent: StreamHandler) => streamSSE("/api/models/create", spec, onEvent),
  deleteModel: (name: string) =>
    request(`/api/models/${name}`, { method: "DELETE" }).then((r) => r.json()),
  imageStatus: () => request("/api/images/status").then((r) => r.json()),
  // /api/health returns 503 (not 200) when overall status is "down" so
  // load balancers/monitoring can act on it — but the body still carries
  // the full per-component payload we want to render either way, so this
  // bypasses the generic `request()` error-throwing path instead of losing
  // that detail behind a generic Error.
  health: async () => {
    const res = await fetch(`${BASE}/api/health`, { headers: authHeaders() });
    const body = await res.json().catch(() => null);
    if (res.ok) return body;
    if (body && body.detail) return body.detail;
    throw new Error(res.statusText);
  },
  activity: () => request("/api/activity").then((r) => r.json()),
  generateImage: (prompt: string, negative: string = "") =>
    request("/api/images/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, negative }),
    }).then((r) => r.json()),

  lockStatus: () => request("/api/lock/status").then((r) => r.json()),
  lockVerify: (passcode: string) =>
    request("/api/lock/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode }),
    }).then((r) => r.json()),
  lockSet: (passcode: string) =>
    request("/api/lock/set", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode }),
    }).then((r) => r.json()),
  lockDisable: (passcode: string) =>
    request("/api/lock/disable", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode }),
    }).then((r) => r.json()),

  getConfig: () => request("/api/config").then((r) => r.json()),
  patchConfig: (patch: Record<string, unknown>) =>
    request("/api/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),
  previewRoute: (params: Record<string, unknown>) =>
    request(`/api/route/preview?${new URLSearchParams(params as Record<string, string>)}`, { method: "POST" }).then((r) =>
      r.json()
    ),

  upload: (file: File, conversationId: string | null = null) => {
    const form = new FormData();
    form.append("file", file);
    if (conversationId) form.append("conversation_id", conversationId);
    return request("/api/upload", { method: "POST", body: form }).then((r) => r.json());
  },

  importHistory: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/import", { method: "POST", body: form }).then((r) => r.json());
  },

  transcribe: (blob: Blob, filename: string = "voice.webm") => {
    const form = new FormData();
    form.append("file", blob, filename);
    return request("/api/voice/transcribe", { method: "POST", body: form }).then((r) => r.json());
  },

  speakUrl: () => `${BASE}/api/voice/speak`,

  listVoices: () => request("/api/voice/voices").then((r) => r.json()),

  /**
   * Streams a chat turn via SSE. Calls `onEvent({type, ...})` for every
   * server-sent event: "route" | "token" | "downgrade" | "done" | "error".
   *
   * Resilience contract (Tier 1 #7):
   *   - If `reader.read()` throws (network drop, sleep, abort) we surface
   *     a final `error` event so the UI can mark the bubble as interrupted
   *     rather than leaving it stuck in "streaming".
   *   - An `AbortError` from the caller's `signal` is treated as a clean
   *     cancellation — no error event, the bubble just stops where it is.
   */
  async streamChat(
    {
      conversationId,
      message,
      attachmentIds,
      webSearch = false,
      agentMode = false,
      deepResearch = false,
      editOf = null,
      regenerateOf = null,
      modelOverride = null,
    }: ChatTurn,
    onEvent: StreamHandler,
    signal?: AbortSignal,
  ) {
    await streamSSE(
      "/api/chat",
      {
        conversation_id: conversationId,
        message,
        attachment_ids: attachmentIds,
        web_search: webSearch,
        agent_mode_on: agentMode,
        deep_research: deepResearch,
        ...(editOf ? { edit_of: editOf } : {}),
        ...(regenerateOf ? { regenerate_of: regenerateOf } : {}),
        ...(modelOverride ? { model_override: modelOverride } : {}),
      },
      onEvent,
      signal,
      // Resume is only wired up for the plain chat path on the backend —
      // agent/deep-research turns have their own multi-step generators.
      !agentMode && !deepResearch ? `/api/conversations/${conversationId}/chat/resume` : null
    );
  },

  /**
   * Council of models: one turn, several models concurrently. Events:
   * "council_start" | "council_token" | "council_error" | "council_done"
   * | "done" | "error". Results persist as branch siblings — see
   * council_service.py.
   */
  async streamCouncil(
    { conversationId, message, attachmentIds, models }: { conversationId: string; message: string; attachmentIds: string[]; models: string[] },
    onEvent: StreamHandler,
    signal?: AbortSignal,
  ) {
    await streamSSE(
      "/api/council",
      { conversation_id: conversationId, message, attachment_ids: attachmentIds, models },
      onEvent,
      signal
    );
  },

  /**
   * Batch job: run one prompt template against every file in a folder,
   * one file at a time. Events per file are the batch_service dicts —
   * {"file", "status": "done"|"error", "result"|"error"} — followed by a
   * final {"status": "done"} frame. Standalone endpoint (see
   * app/api/batch.py); not yet wired into the main chat flow.
   */
  async runBatch(
    { folderPath, promptTemplate, model, extensions }: { folderPath: string; promptTemplate: string; model?: string | null; extensions?: string[] | null },
    onEvent: StreamHandler,
    signal?: AbortSignal,
  ) {
    await streamSSE(
      "/api/batch/run",
      { folder_path: folderPath, prompt_template: promptTemplate, model, extensions },
      onEvent,
      signal
    );
  },
};
