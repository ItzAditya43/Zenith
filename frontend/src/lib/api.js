const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8420";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options);
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

async function streamSSE(path, body, onEvent, signal) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
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
          onEvent(JSON.parse(line.slice(5).trim()));
        } catch (_) {
          /* ignore malformed chunk */
        }
      }
    }
  } catch (err) {
    if (err && err.name === "AbortError") return;
    onEvent({ type: "error", message: `Stream interrupted: ${err.message || err}` });
  }
}

export const api = {
  base: BASE,

  listConversations: () => request("/api/conversations").then((r) => r.json()),
  createConversation: (title = "New chat") =>
    request("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
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

  listModels: () => request("/api/models").then((r) => r.json()),
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
      },
      onEvent,
      signal
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