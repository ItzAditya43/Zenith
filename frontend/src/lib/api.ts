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
    const url = new URL(location.origin);
    url.port = port;
    return url.origin;
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
  setConversationWorkdir: (conversationId: string, workdir: string) =>
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
  createSchedule: (name: string, prompt: string, mode: string, intervalMinutes: number) =>
    request("/api/schedules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, prompt, mode, interval_minutes: intervalMinutes }),
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

  listProjects: () => request("/api/projects").then((r) => r.json()),
  createProject: (name: string, workdir: string) =>
    request("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, workdir }),
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

  listMemories: () => request("/api/memories").then((r) => r.json()),
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
  clearMemories: () => request("/api/memories", { method: "DELETE" }),
  reviewMemoryConflicts: () => request("/api/memories/review-conflicts", { method: "POST" }).then((r) => r.json()),
  listMemoryConflicts: () => request("/api/memories/conflicts").then((r) => r.json()),
  resolveMemoryConflict: (id: string) => request(`/api/memories/conflicts/${id}/resolve`, { method: "POST" }),

  approveToolCall: (id: string) => request(`/api/agent/tool-calls/${id}/approve`, { method: "POST" }),
  denyToolCall: (id: string) => request(`/api/agent/tool-calls/${id}/deny`, { method: "POST" }),
  revertToolCall: (id: string) =>
    request(`/api/agent/tool-calls/${id}/revert`, { method: "POST" }).then((r) => r.json()),
  listToolCalls: (conversationId: string) =>
    request(`/api/agent/tool-calls?conversation_id=${encodeURIComponent(conversationId)}`).then((r) => r.json()),
  revertRun: (runId: string) => request(`/api/agent/runs/${runId}/revert`, { method: "POST" }).then((r) => r.json()),

  listModels: () => request("/api/models").then((r) => r.json()),
  // Settings change history — see settings_history_service.py.
  getSettingsHistory: (key: string | null = null, limit: number = 100) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (key) params.set("key", key);
    return request(`/api/settings/history?${params.toString()}`).then((r) => r.json());
  },
  revertSettingsHistory: (id: string) =>
    request(`/api/settings/history/${id}/revert`, { method: "POST" }).then((r) => r.json()),
  getRoutingStatus: () => request("/api/routing/status").then((r) => r.json()),
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
