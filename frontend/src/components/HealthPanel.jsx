import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const LABELS = {
  ollama: "Ollama",
  whisper: "Whisper (speech-to-text)",
  tts: "Text-to-speech",
  vector_search: "Vector search (RAG)",
  image_gen: "Image generation",
  agent_mode: "Agent mode",
  mcp: "MCP servers",
};

// Fields already surfaced via the dot/label — don't repeat them in the
// generic detail line.
const HIDDEN_FIELDS = new Set(["ok"]);

function StatusDot({ ok }) {
  return <span className={`health-dot ${ok ? "is-ok" : "is-down"}`} aria-hidden="true" />;
}

function ComponentRow({ id, data }) {
  const label = LABELS[id] || id;
  const entries = Object.entries(data || {}).filter(([k]) => !HIDDEN_FIELDS.has(k));
  return (
    <div className="health-row">
      <div className="health-row-main">
        <StatusDot ok={!!data?.ok} />
        <span className="health-row-label">{label}</span>
      </div>
      {entries.length > 0 && (
        <div className="health-row-detail">
          {entries.map(([k, v]) => (
            <span key={k} className="health-row-field">
              {k}: {String(v)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Renders the /api/health probe results — one dot + detail line per
 * dependency (Ollama, Whisper, TTS, vector search, image gen, agent mode,
 * MCP servers). Checked on open, not live-polled; use the refresh button
 * for a fresh read. Mirrors UsageDashboard's overlay/dialog structure. */
export default function HealthPanel({ onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .health()
      .then((res) => setData(res))
      .catch((err) => setError(err.message || "Failed to check health."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const components = data?.components ? Object.entries(data.components) : [];

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div
        className="calendar-modal"
        style={{ width: "min(480px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="health-panel-title"
      >
        <div className="calendar-header">
          <span id="health-panel-title">System health</span>
          <div style={{ display: "flex", gap: "var(--space-1)" }}>
            <button className="icon-btn" onClick={load} title="Refresh" aria-label="Refresh">
              <Icon name="rotate-ccw" size={14} />
            </button>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
        <div style={{ padding: "var(--space-3) var(--space-4)", maxHeight: "75vh", overflowY: "auto" }}>
          {loading && !data && <p className="conversation-empty">Checking…</p>}
          {error && !data && <p className="conversation-empty">{error}</p>}
          {data && (
            <>
              <div className={`health-overall health-overall-${data.status}`}>
                <StatusDot ok={data.status === "ok"} />
                <span>Overall: {data.status}</span>
              </div>
              <div className="health-list">
                {components.map(([id, componentData]) => (
                  <ComponentRow key={id} id={id} data={componentData} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
