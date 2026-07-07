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

  /**
   * Streams a chat turn via SSE. Calls `onEvent({type, ...})` for every
   * server-sent event: "route" | "token" | "done" | "error".
   */
  async streamChat({ conversationId, message, attachmentIds }, onEvent, signal) {
    const res = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: conversationId,
        message,
        attachment_ids: attachmentIds,
      }),
      signal,
    });
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
  },
};
