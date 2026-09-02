import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

// Mirrors lib/api.js's own base-URL + unlock-header resolution (not
// exported from there, so duplicated here rather than editing that file
// for one extra read-only fetch). Keep in sync if that logic changes.
const JOBS_BACKEND_PORT = "8420";
function jobsBase() {
  const explicit = import.meta.env.VITE_API_BASE;
  if (explicit) return explicit;
  if (typeof window !== "undefined" && window.location?.hostname) {
    const { protocol, hostname } = window.location;
    return `${protocol}//${hostname}:${JOBS_BACKEND_PORT}`;
  }
  return "http://localhost:8420";
}
function jobsUnlockHeaders() {
  const token = sessionStorage.getItem("zenith-unlock");
  return token ? { "X-Zenith-Unlock": token } : {};
}

function relativeTime(epochSeconds) {
  if (!epochSeconds) return "never";
  const diffMs = Date.now() - epochSeconds * 1000;
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}

function JobRow({ job }) {
  return (
    <div className="health-row">
      <div className="health-row-main">
        <StatusDot ok={job.last_status === "success"} />
        <span className="health-row-label">{job.name}</span>
      </div>
      <div className="health-row-detail">
        <span className="health-row-field">last run: {relativeTime(job.last_run_at)}</span>
        <span className="health-row-field">
          duration: {job.last_duration_ms != null ? `${Math.round(job.last_duration_ms)}ms` : "—"}
        </span>
        {job.last_detail && <span className="health-row-field">{job.last_detail}</span>}
      </div>
    </div>
  );
}

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
  const [jobs, setJobs] = useState(null);
  const [jobsError, setJobsError] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .health()
      .then((res) => setData(res))
      .catch((err) => setError(err.message || "Failed to check health."))
      .finally(() => setLoading(false));

    setJobsError(null);
    fetch(`${jobsBase()}/api/jobs/status`, { headers: jobsUnlockHeaders() })
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(res.statusText))))
      .then((res) => setJobs(res))
      .catch((err) => setJobsError(err.message || "Failed to load background job status."));
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
              <div className="health-overall" style={{ marginTop: "var(--space-3)" }}>
                <span>Background jobs</span>
              </div>
              <div className="health-list">
                {jobsError && <p className="conversation-empty">{jobsError}</p>}
                {!jobsError && jobs && jobs.length === 0 && (
                  <p className="conversation-empty">No jobs have run yet.</p>
                )}
                {!jobsError && jobs && jobs.map((job) => <JobRow key={job.name} job={job} />)}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
