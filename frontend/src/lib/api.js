// API base resolution, in priority order:
//   1. An explicit VITE_API_BASE (set at build/deploy time) always wins.
//   2. Otherwise derive it from wherever the frontend itself was loaded — same
//      hostname, backend port 8420. This is what makes multi-device access work:
//      open the app from a phone at http://192.168.1.5:5173 (or a Tailscale
//      hostname) and it talks to the backend at that same host, not "localhost"
//      (which on the phone would mean the phone itself).
//   3. Fall back to localhost for SSR/other odd contexts.
const BACKEND_PORT = "8420";
function resolveBase() {
  const explicit = import.meta.env.VITE_API_BASE;
  if (explicit) return explicit;
  if (typeof window !== "undefined" && window.location?.hostname) {
    const { protocol, hostname } = window.location;
    return `${protocol}//${hostname}:${BACKEND_PORT}`;
  }
  return "http://localhost:8420";
}
const BASE = resolveBase();

// App-level passcode lock: the unlock token (issued by /api/lock/verify) is
// stored in sessionStorage and sent on every request so the backend's lock
// middleware lets it through.
function unlockHeaders() {
  const token = sessionStorage.getItem("zenith-unlock");
  return token ? { "X-Zenith-Unlock": token } : {};
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { ...unlockHeaders(), ...(options.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res;
}

/** Reads one SSE response body, forwarding parsed frames to onEvent.
 * Returns "done" | "error" | "interrupted" (reader threw — the caller
 * decides whether that's resumable) | "clean-end" (stream closed with
 * no explicit done/error, e.g. an AbortError further up already handled). */
async function consumeSSEBody(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let sawTerminal = null;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        try {
          const ev = JSON.parse(line.slice(5).trim());
          onEvent(ev);
          if (ev.type === "done" || ev.type === "error") sawTerminal = ev.type;
        } catch (_) {
          /* ignore malformed chunk */
        }
      }
    }
  } catch (err) {
    if (err && err.name === "AbortError") return "clean-end";
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
async function streamSSE(path, body, onEvent, signal, resumePath = null) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...unlockHeaders() },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err && err.name === "AbortError") return;
    onEvent({ type: "error", message: `Network error: ${err.message || err}` });
    return;
  }
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch (_) {}
    onEvent({ type: "error", message: detail });
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
    let resumeRes;
    try {
      resumeRes = await fetch(`${BASE}${resumePath}`, { headers: unlockHeaders(), signal });
    } catch (err) {
      if (err && err.name === "AbortError") return;
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

export const api = {
  base: BASE,

  listConversations: () => request("/api/conversations").then((r) => r.json()),
  createConversation: (title = "New chat", projectId = null) =>
    request("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, project_id: projectId }),
    }).then((r) => r.json()),
  renameConversation: (id, title) =>
    request(`/api/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (id) => request(`/api/conversations/${id}`, { method: "DELETE" }),
  getMessages: (id) => request(`/api/conversations/${id}/messages`).then((r) => r.json()),
  setTitle: (id, title) =>
    request(`/api/conversations/${id}/title`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).then((r) => r.json()),
  searchConversations: (query) =>
    request(`/api/conversations/search?q=${encodeURIComponent(query)}`).then((r) => r.json()),
  searchAll: (query) =>
    request(`/api/search/all?q=${encodeURIComponent(query)}`).then((r) => r.json()),

  listPersonas: () => request("/api/personas").then((r) => r.json()),
  createPersona: (name, systemPrompt, icon = null) =>
    request("/api/personas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, system_prompt: systemPrompt, icon }),
    }).then((r) => r.json()),
  updatePersona: (id, patch) =>
    request(`/api/personas/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  deletePersona: (id) => request(`/api/personas/${id}`, { method: "DELETE" }),
  setConversationPersona: (conversationId, personaId) =>
    request(`/api/conversations/${conversationId}/persona`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona_id: personaId }),
    }),
  setConversationWorkdir: (conversationId, workdir) =>
    request(`/api/conversations/${conversationId}/workdir`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workdir }),
    }).then((r) => r.json()),

  exportUrl: (format) => `${BASE}/api/export/${format}`,

  listWorkspaceFiles: (conversationId, path = "") =>
    request(`/api/conversations/${conversationId}/files?path=${encodeURIComponent(path)}`).then((r) => r.json()),
  readWorkspaceFile: (conversationId, path) =>
    request(`/api/conversations/${conversationId}/files/content?path=${encodeURIComponent(path)}`).then((r) => r.json()),
  writeWorkspaceFile: (conversationId, path, content) =>
    request(`/api/conversations/${conversationId}/files/content?path=${encodeURIComponent(path)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }).then((r) => r.json()),

  editDocument: (attachmentId, instruction) =>
    request(`/api/documents/${attachmentId}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    }).then((r) => r.json()),
  attachmentDownloadUrl: (attachmentId) => `${BASE}/api/attachments/${attachmentId}/download`,

  listFolders: () => request("/api/folders").then((r) => r.json()),
  addFolder: (path, extensions = null) =>
    request("/api/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, extensions }),
    }).then((r) => r.json()),
  toggleFolder: (id, enabled) =>
    request(`/api/folders/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  removeFolder: (id) => request(`/api/folders/${id}`, { method: "DELETE" }),
  scanFolderNow: (id) => request(`/api/folders/${id}/scan`, { method: "POST" }).then((r) => r.json()),

  listSchedules: () => request("/api/schedules").then((r) => r.json()),
  createSchedule: (name, prompt, mode, intervalMinutes) =>
    request("/api/schedules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, prompt, mode, interval_minutes: intervalMinutes }),
    }).then((r) => r.json()),
  toggleSchedule: (id, enabled) =>
    request(`/api/schedules/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  deleteSchedule: (id) => request(`/api/schedules/${id}`, { method: "DELETE" }),
  listScheduleRuns: (id) => request(`/api/schedules/${id}/runs`).then((r) => r.json()),
  recentScheduleRuns: (since) => request(`/api/schedules/recent-runs?since=${since}`).then((r) => r.json()),
  runScheduleNow: (id) => request(`/api/schedules/${id}/run-now`, { method: "POST" }).then((r) => r.json()),

  listMcpServers: () => request("/api/mcp/servers").then((r) => r.json()),
  addMcpServer: (name, command, args = [], env = {}) =>
    request("/api/mcp/servers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, command, args, env }),
    }).then((r) => r.json()),
  toggleMcpServer: (id, enabled) =>
    request(`/api/mcp/servers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  removeMcpServer: (id) => request(`/api/mcp/servers/${id}`, { method: "DELETE" }),
  getMcpServerTools: (id) => request(`/api/mcp/servers/${id}/tools`).then((r) => r.json()),

  listBranches: (conversationId) =>
    request(`/api/conversations/${conversationId}/branches`).then((r) => r.json()),
  activateBranch: (conversationId, messageId) =>
    request(`/api/conversations/${conversationId}/messages/${messageId}/activate`, {
      method: "POST",
    }).then((r) => r.json()),
  deleteMessage: (conversationId, messageId) =>
    request(`/api/conversations/${conversationId}/messages/${messageId}`, {
      method: "DELETE",
    }).then((r) => r.json()),

  hardwareReport: () => request("/api/hardware").then((r) => r.json()),
  usageSummary: (days = 14) => request(`/api/usage/summary?days=${days}`).then((r) => r.json()),

  emailTest: () => request("/api/email/test").then((r) => r.json()),
  emailFlags: () => request("/api/email/flags").then((r) => r.json()),
  markEmailFlagsSeen: () => request("/api/email/flags/mark-seen", { method: "POST" }),
  emailMessages: () => request("/api/email/messages").then((r) => r.json()),
  emailMessage: (id) => request(`/api/email/messages/${id}`).then((r) => r.json()),
  emailSummarize: (id) =>
    request(`/api/email/messages/${id}/summarize`, { method: "POST" }).then((r) => r.json()),
  emailDraftReply: (id, instruction = "") =>
    request(`/api/email/messages/${id}/draft-reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    }).then((r) => r.json()),
  emailSend: (to, subject, body, inReplyTo = null) =>
    request("/api/email/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to, subject, body, in_reply_to: inReplyTo }),
    }).then((r) => r.json()),

  syncPairStart: () => request("/api/sync/pair/start", { method: "POST" }).then((r) => r.json()),
  syncPairBundle: (baseUrl, code) =>
    fetch(`${baseUrl}/api/sync/pair/bundle?code=${encodeURIComponent(code)}`).then((r) => {
      if (!r.ok) throw new Error("Invalid, expired, or already-used code.");
      return r.json();
    }),
  syncPairComplete: (code, encryptedSecret) =>
    request("/api/sync/pair/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, encrypted_secret: encryptedSecret }),
    }).then((r) => r.json()),
  syncExport: (passphrase) =>
    request("/api/sync/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase }),
    }).then((r) => r.json()),
  syncImport: (passphrase, blob) =>
    request("/api/sync/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase, blob }),
    }).then((r) => r.json()),

  getGroupPersonas: (conversationId) =>
    request(`/api/conversations/${conversationId}/group-personas`).then((r) => r.json()),
  setGroupPersonas: (conversationId, personaIds) =>
    request(`/api/conversations/${conversationId}/group-personas`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona_ids: personaIds }),
    }).then((r) => r.json()),
  streamGroupChat: (conversationId, message, onEvent, signal) =>
    streamSSE(`/api/conversations/${conversationId}/group-chat`, { message }, onEvent, signal),

  listResearchReports: () => request("/api/research/reports").then((r) => r.json()),
  getResearchReport: (id) => request(`/api/research/reports/${id}`).then((r) => r.json()),
  deleteResearchReport: (id) => request(`/api/research/reports/${id}`, { method: "DELETE" }),
  askResearchReport: (id, question) =>
    request(`/api/research/reports/${id}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }).then((r) => r.json()),

  listTodos: () => request("/api/todos").then((r) => r.json()),
  createTodo: (text, dueTs = null) =>
    request("/api/todos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, due_ts: dueTs }),
    }).then((r) => r.json()),
  updateTodo: (id, patch) =>
    request(`/api/todos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),
  deleteTodo: (id) => request(`/api/todos/${id}`, { method: "DELETE" }),

  listNotes: () => request("/api/notes").then((r) => r.json()),
  createNote: (content, color = "default") =>
    request("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, color }),
    }).then((r) => r.json()),
  updateNote: (id, patch) =>
    request(`/api/notes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),
  deleteNote: (id) => request(`/api/notes/${id}`, { method: "DELETE" }),

  listCalendarEvents: (fromTs, toTs) =>
    request(`/api/calendar/events?from_ts=${fromTs}&to_ts=${toTs}`).then((r) => r.json()),
  createCalendarEvent: (event) =>
    request("/api/calendar/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    }).then((r) => r.json()),
  deleteCalendarEvent: (id) => request(`/api/calendar/events/${id}`, { method: "DELETE" }),

  listProjects: () => request("/api/projects").then((r) => r.json()),
  createProject: (name, workdir) =>
    request("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, workdir }),
    }).then((r) => r.json()),
  deleteProject: (id) => request(`/api/projects/${id}`, { method: "DELETE" }),
  setConversationProject: (conversationId, projectId) =>
    request(`/api/conversations/${conversationId}/project`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId }),
    }).then((r) => r.json()),
  setProjectAgentMode: (projectId, agentMode) =>
    request(`/api/projects/${projectId}/agent-mode`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_mode: agentMode }),
    }).then((r) => r.json()),

  setConversationPinned: (conversationId, pinned) =>
    request(`/api/conversations/${conversationId}/pin`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned }),
    }).then((r) => r.json()),
  setConversationTags: (conversationId, tags) =>
    request(`/api/conversations/${conversationId}/tags`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags }),
    }).then((r) => r.json()),

  shareConversation: (conversationId) =>
    request(`/api/conversations/${conversationId}/share`, { method: "POST" }).then((r) => r.json()),
  unshareConversation: (conversationId) =>
    request(`/api/conversations/${conversationId}/share`, { method: "DELETE" }).then((r) => r.json()),
  getSharedConversation: (token) =>
    fetch(`${BASE}/api/share/${token}`).then((r) => {
      if (!r.ok) throw new Error("This link is invalid or has been revoked.");
      return r.json();
    }),
  shareUrl: (token) => `${window.location.origin}${window.location.pathname}#/share/${token}`,
  extractProject: (conversationId) =>
    request(`/api/conversations/${conversationId}/extract-project`, { method: "POST" }).then((r) => r.json()),

  listSnippets: () => request("/api/snippets").then((r) => r.json()),
  createSnippet: (title, content) =>
    request("/api/snippets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content }),
    }).then((r) => r.json()),
  deleteSnippet: (id) => request(`/api/snippets/${id}`, { method: "DELETE" }),

  gitStatus: (conversationId) =>
    request(`/api/conversations/${conversationId}/git/status`).then((r) => r.json()),
  gitDiff: (conversationId, path = "") =>
    request(`/api/conversations/${conversationId}/git/diff?path=${encodeURIComponent(path)}`).then((r) => r.json()),
  runChecks: (conversationId, command = null) =>
    request(`/api/conversations/${conversationId}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(command ? { command } : {}),
    }).then((r) => r.json()),

  listSkills: () => request("/api/skills").then((r) => r.json()),
  deleteSkill: (id) => request(`/api/skills/${id}`, { method: "DELETE" }),

  listMemories: () => request("/api/memories").then((r) => r.json()),
  addMemory: (content, category = "fact") =>
    request("/api/memories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, category }),
    }).then((r) => r.json()),
  toggleMemory: (id, enabled) =>
    request(`/api/memories/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  deleteMemory: (id) => request(`/api/memories/${id}`, { method: "DELETE" }),
  clearMemories: () => request("/api/memories", { method: "DELETE" }),

  approveToolCall: (id) => request(`/api/agent/tool-calls/${id}/approve`, { method: "POST" }),
  denyToolCall: (id) => request(`/api/agent/tool-calls/${id}/deny`, { method: "POST" }),
  revertToolCall: (id) =>
    request(`/api/agent/tool-calls/${id}/revert`, { method: "POST" }).then((r) => r.json()),
  listToolCalls: (conversationId) =>
    request(`/api/agent/tool-calls?conversation_id=${encodeURIComponent(conversationId)}`).then((r) => r.json()),
  revertRun: (runId) => request(`/api/agent/runs/${runId}/revert`, { method: "POST" }).then((r) => r.json()),

  listModels: () => request("/api/models").then((r) => r.json()),
  getRoutingStatus: () => request("/api/routing/status").then((r) => r.json()),
  pullModel: (name, onEvent) => streamSSE("/api/models/pull", { name }, onEvent),
  createModel: (spec, onEvent) => streamSSE("/api/models/create", spec, onEvent),
  deleteModel: (name) =>
    request(`/api/models/${name}`, { method: "DELETE" }).then((r) => r.json()),
  imageStatus: () => request("/api/images/status").then((r) => r.json()),
  activity: () => request("/api/activity").then((r) => r.json()),
  generateImage: (prompt, negative = "") =>
    request("/api/images/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, negative }),
    }).then((r) => r.json()),

  lockStatus: () => request("/api/lock/status").then((r) => r.json()),
  lockVerify: (passcode) =>
    request("/api/lock/verify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode }),
    }).then((r) => r.json()),
  lockSet: (passcode) =>
    request("/api/lock/set", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode }),
    }).then((r) => r.json()),
  lockDisable: (passcode) =>
    request("/api/lock/disable", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passcode }),
    }).then((r) => r.json()),

  getConfig: () => request("/api/config").then((r) => r.json()),
  patchConfig: (patch) =>
    request("/api/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }).then((r) => r.json()),
  previewRoute: (params) =>
    request(`/api/route/preview?${new URLSearchParams(params)}`, { method: "POST" }).then((r) =>
      r.json()
    ),

  upload: (file, conversationId = null) => {
    const form = new FormData();
    form.append("file", file);
    if (conversationId) form.append("conversation_id", conversationId);
    return request("/api/upload", { method: "POST", body: form }).then((r) => r.json());
  },

  importHistory: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/import", { method: "POST", body: form }).then((r) => r.json());
  },

  transcribe: (blob, filename = "voice.webm") => {
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
    },
    onEvent,
    signal
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
  async streamCouncil({ conversationId, message, attachmentIds, models }, onEvent, signal) {
    await streamSSE(
      "/api/council",
      { conversation_id: conversationId, message, attachment_ids: attachmentIds, models },
      onEvent,
      signal
    );
  },
};