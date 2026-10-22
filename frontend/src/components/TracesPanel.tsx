import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useEscapeToClose } from "../hooks/useEscapeToClose";

interface ToolCall {
  tool: string;
  risk?: string;
  status: string;
  ok?: boolean;
  ms?: number;
  subagent?: boolean;
}

interface Trace {
  id: string;
  mode: string;
  user_text: string | null;
  model: string | null;
  role: string | null;
  reason: string | null;
  confidence: number | null;
  sources: { kind?: string; url?: string; title?: string; source_id?: string }[];
  tool_calls: ToolCall[];
  token_count: number | null;
  first_token_ms: number | null;
  total_ms: number | null;
  downgraded_to: string | null;
  status: string;
  error: string | null;
  created_at: number;
}

const secs = (ms: number | null) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)}s`);

/** "Why did this reply come out like that?" — one row per turn: routing
 * decision, what was pulled into context, every tool call, and timing.
 * Backed by /api/traces (backend/app/services/trace_service.py). */
export default function TracesPanel({ conversationId, onClose }: { conversationId?: string | null; onClose: () => void }) {
  const [traces, setTraces] = useState<Trace[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEscapeToClose(onClose);

  useEffect(() => {
    api.listTraces(conversationId ?? null)
      .then((t: Trace[]) => setTraces(t))
      .catch((err: Error) => setError(err.message));
  }, [conversationId]);

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div className="calendar-modal" style={{ width: "min(680px, calc(100vw - 2rem))" }}
        onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="traces-title">
        <div className="calendar-header">
          <span id="traces-title">Turn traces{conversationId ? " — this chat" : ""}</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div style={{ padding: "var(--space-3) var(--space-4)", maxHeight: "75vh", overflowY: "auto" }}>
          {error && <p className="conversation-empty">{error}</p>}
          {traces && traces.length === 0 && <p className="conversation-empty">No turns traced yet.</p>}
          <div className="health-list">
            {traces?.map((t) => (
              <div key={t.id} className="health-row">
                <button className="health-row-main" style={{ all: "unset", cursor: "pointer", display: "block" }}
                  onClick={() => setOpen(open === t.id ? null : t.id)} aria-expanded={open === t.id}>
                  <span className="health-row-label">
                    {t.status === "ok" ? "✓" : "✕"} [{t.mode}] {(t.user_text || "").slice(0, 70)}
                  </span>
                </button>
                <div className="health-row-detail">
                  <span className="health-row-field">{t.model ?? "?"}{t.downgraded_to ? ` → ${t.downgraded_to}` : ""}</span>
                  <span className="health-row-field">first token {secs(t.first_token_ms)} · total {secs(t.total_ms)}</span>
                  <span className="health-row-field">{t.token_count ?? 0} chunks</span>
                  {t.tool_calls.length > 0 && <span className="health-row-field">{t.tool_calls.length} tool calls</span>}
                  <span className="health-row-field">{new Date(t.created_at * 1000).toLocaleString()}</span>
                </div>
                {open === t.id && (
                  <div className="health-row-detail" style={{ flexDirection: "column", alignItems: "flex-start" }}>
                    <span className="health-row-field">
                      route: {t.role} — {t.reason}{t.confidence != null ? ` (confidence ${t.confidence.toFixed(2)})` : ""}
                    </span>
                    {t.sources.map((s, i) => (
                      <span key={i} className="health-row-field">context: [{s.kind ?? "web"}] {s.title || s.url || s.source_id}</span>
                    ))}
                    {t.tool_calls.map((c, i) => (
                      <span key={i} className="health-row-field">
                        {c.subagent ? "↳ " : ""}{c.tool} · {c.risk} · {c.status}{c.ok === false ? " (error)" : ""}{c.ms != null ? ` · ${secs(c.ms)}` : ""}
                      </span>
                    ))}
                    {t.error && <span className="health-row-field">error: {t.error}</span>}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
