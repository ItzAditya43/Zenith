/**
 * A small Zenith API client for TypeScript / JavaScript (browser, Node 18+, Deno, Bun).
 *
 *   const z = new Zenith("http://127.0.0.1:8420", "zk_...");
 *   const { id } = await z.newChat("From a script");
 *   for await (const text of z.chat(id, "Summarise today's news")) process.stdout.write(text);
 */
export type ZenithEvent = { type: string; [k: string]: unknown };

export class Zenith {
  constructor(private base = "http://127.0.0.1:8420", private key?: string) {
    this.base = base.replace(/\/$/, "");
  }

  private headers(extra: Record<string, string> = {}) {
    return { ...(this.key ? { Authorization: `Bearer ${this.key}` } : {}), ...extra };
  }

  private async json<T>(method: string, path: string, body?: unknown): Promise<T> {
    const r = await fetch(this.base + path, {
      method,
      headers: this.headers(body ? { "Content-Type": "application/json" } : {}),
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error(`${r.status}: ${(await r.json().catch(() => ({}))).detail ?? r.statusText}`);
    return r.json() as Promise<T>;
  }

  version() { return this.json<{ api_version: string; app_version: string }>("GET", "/api/version"); }
  models() { return this.json<{ name: string }[]>("GET", "/api/models"); }
  conversations() { return this.json<{ id: string; title: string }[]>("GET", "/api/conversations"); }
  newChat(title = "New chat") { return this.json<{ id: string }>("POST", "/api/conversations", { title }); }
  messages(id: string) { return this.json<{ role: string; content: string }[]>("GET", `/api/conversations/${id}/messages`); }
  async notifications(since?: number) {
    return (await this.json<{ items: unknown[] }>("GET", `/api/notifications${since ? `?since=${since}` : ""}`)).items;
  }

  async upload(file: Blob, name: string, conversationId?: string) {
    const form = new FormData();
    form.append("file", file, name);
    if (conversationId) form.append("conversation_id", conversationId);
    const r = await fetch(`${this.base}/api/upload`, { method: "POST", headers: this.headers(), body: form });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json() as Promise<{ id: string; filename: string }>;
  }

  /** Every streamed event: route, sources, token, done, error… */
  async *chatEvents(conversationId: string, message: string, opts: { attachments?: string[]; model?: string } = {}) {
    const r = await fetch(`${this.base}/api/chat`, {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ conversation_id: conversationId, message, attachment_ids: opts.attachments ?? [], model_override: opts.model ?? null }),
    });
    if (!r.ok || !r.body) throw new Error(`${r.status}`);
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5)) as ZenithEvent;
        yield ev;
        if (ev.type === "done" || ev.type === "error") return;
      }
    }
  }

  /** Just the reply text, as it streams. */
  async *chat(conversationId: string, message: string, opts: { attachments?: string[]; model?: string } = {}) {
    for await (const ev of this.chatEvents(conversationId, message, opts)) {
      if (ev.type === "token") yield String(ev.text ?? "");
      if (ev.type === "error") throw new Error(String(ev.message ?? "chat failed"));
    }
  }
}
