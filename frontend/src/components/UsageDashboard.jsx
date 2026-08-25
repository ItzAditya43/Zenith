import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

function Bar({ value, max, label, sub }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 2;
  return (
    <div className="usage-bar-col" title={`${label}: ${sub}`}>
      <div className="usage-bar-track">
        <div className="usage-bar-fill" style={{ height: `${pct}%` }} />
      </div>
      <span className="usage-bar-label">{label}</span>
    </div>
  );
}

/** Token throughput + latency trends over time, and disk usage — the
 * "how has this actually been performing" view, distinct from the
 * live-only status rail. Hand-rolled CSS bars, no charting dependency. */
// Rough, honestly-approximate reference rate for the "compute cost avoided"
// estimate below — real cloud API pricing varies widely by provider and
// model tier. This is directional, not a precise figure.
const ILLUSTRATIVE_CLOUD_RATE_PER_1M_TOKENS = 3;

export default function UsageDashboard({ onClose }) {
  const [data, setData] = useState(null);
  const [stats, setStats] = useState(null);
  const [days, setDays] = useState(14);

  useEffect(() => {
    api.usageSummary(days).then(setData).catch(() => {});
    api.usageStats(days).then(setStats).catch(() => {});
  }, [days]);

  if (!data) {
    return (
      <div className="calendar-overlay" onClick={onClose}>
        <div className="calendar-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="usage-dashboard-title">
          <div className="calendar-header">
            <span id="usage-dashboard-title">Usage & diagnostics</span>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
          <p className="conversation-empty">Loading…</p>
        </div>
      </div>
    );
  }

  const maxTokens = Math.max(1, ...data.daily.map((d) => d.tokens));
  const maxLatency = Math.max(1, ...data.daily.map((d) => d.avg_duration_ms));

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div className="calendar-modal" style={{ width: "min(680px, calc(100vw - 3rem))" }} onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="usage-dashboard-title">
        <div className="calendar-header">
          <span id="usage-dashboard-title">Usage & diagnostics</span>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div style={{ padding: "var(--space-3) var(--space-4)", maxHeight: "75vh", overflowY: "auto" }}>
          <div className="settings-row" style={{ marginBottom: "var(--space-3)" }}>
            {[7, 14, 30].map((d) => (
              <button
                key={d}
                className={`text-btn ${days === d ? "is-active" : ""}`}
                onClick={() => setDays(d)}
              >
                {d}d
              </button>
            ))}
          </div>

          <div className="hw-summary">
            <span>{data.totals.turns} turns</span>
            <span>{data.totals.tokens} tokens</span>
            <span>{Math.round(data.totals.avg_duration_ms)}ms avg</span>
            <span>{Math.round(data.totals.avg_first_token_ms)}ms to first token</span>
          </div>

          {data.daily.length > 0 && (
            <>
              <h3 className="settings-section-title" style={{ marginTop: "var(--space-4)" }}>
                Tokens per day
              </h3>
              <div className="usage-bar-row">
                {data.daily.map((d) => (
                  <Bar key={d.day} value={d.tokens} max={maxTokens} label={d.day.slice(5)} sub={`${d.tokens} tokens`} />
                ))}
              </div>

              <h3 className="settings-section-title" style={{ marginTop: "var(--space-4)" }}>
                Avg latency per day
              </h3>
              <div className="usage-bar-row">
                {data.daily.map((d) => (
                  <Bar
                    key={d.day}
                    value={d.avg_duration_ms}
                    max={maxLatency}
                    label={d.day.slice(5)}
                    sub={`${Math.round(d.avg_duration_ms)}ms`}
                  />
                ))}
              </div>
            </>
          )}
          {data.daily.length === 0 && (
            <p className="conversation-empty" style={{ marginTop: "var(--space-3)" }}>
              No usage recorded in this window yet.
            </p>
          )}

          {data.by_model.length > 0 && (
            <>
              <h3 className="settings-section-title" style={{ marginTop: "var(--space-4)" }}>
                By model
              </h3>
              <ul className="model-list">
                {data.by_model.map((m) => (
                  <li key={m.model}>
                    <span className="model-name" style={{ flex: 1 }}>{m.model}</span>
                    <span className="setting-hint">
                      {m.turns} turns · {m.tokens} tokens · {Math.round(m.avg_duration_ms)}ms avg
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {stats?.latency_percentiles?.count > 0 && (
            <>
              <h3 className="settings-section-title" style={{ marginTop: "var(--space-4)" }}>
                Latency percentiles
              </h3>
              <div className="hw-summary">
                <span>p50: {stats.latency_percentiles.p50_ms}ms</span>
                <span>p90: {stats.latency_percentiles.p90_ms}ms</span>
                <span>p99: {stats.latency_percentiles.p99_ms}ms</span>
              </div>
            </>
          )}

          {stats?.by_model?.length > 0 && (
            <>
              <h3 className="settings-section-title" style={{ marginTop: "var(--space-4)" }}>
                Model comparison
              </h3>
              <ul className="model-list">
                {stats.by_model.map((m) => (
                  <li key={m.model}>
                    <span className="model-name" style={{ flex: 1 }}>{m.model}</span>
                    <span className="setting-hint">
                      {m.turns} turns · {Math.round(m.avg_duration_ms)}ms avg
                      {m.avg_tokens_per_sec != null ? ` · ${m.avg_tokens_per_sec} tok/s` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {data.totals.tokens > 0 && (
            <>
              <h3 className="settings-section-title" style={{ marginTop: "var(--space-4)" }}>
                Compute cost avoided (rough estimate)
              </h3>
              <p className="conversation-empty" style={{ marginTop: 0, textAlign: "left" }}>
                {data.totals.tokens.toLocaleString()} tokens generated locally in this window ≈
                {" "}
                ${((data.totals.tokens / 1_000_000) * ILLUSTRATIVE_CLOUD_RATE_PER_1M_TOKENS).toFixed(2)}
                {" "}
                if run through a typical cloud API at ~${ILLUSTRATIVE_CLOUD_RATE_PER_1M_TOKENS}/1M tokens.
                Illustrative only — actual cloud pricing varies widely by provider and model tier.
              </p>
            </>
          )}

          <h3 className="settings-section-title" style={{ marginTop: "var(--space-4)" }}>
            Disk
          </h3>
          <div className="hw-summary">
            <span>{data.disk.data_dir_size_mb ?? "?"} MB data</span>
            <span>{data.disk.db_size_mb ?? "?"} MB database</span>
            <span>{data.disk.free_gb ?? "?"} GB free</span>
          </div>
        </div>
      </div>
    </div>
  );
}
