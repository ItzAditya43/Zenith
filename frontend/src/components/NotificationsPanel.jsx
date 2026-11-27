import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { openTasks } from "../lib/uiEvents.js";
import Icon from "./Icon.jsx";

function when(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Everything that notified (or would have): searchable history plus
 * which kinds pop up on the desktop and when to stay quiet. */
export default function NotificationsPanel({ onClose, notificationsEnabled, onEnableDesktop }) {
  const [data, setData] = useState({ items: [], labels: {}, unread: 0, quiet_now: false });
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [config, setConfig] = useState(null);
  const [tab, setTab] = useState("history");

  const load = useCallback(() => api.listNotifications({ q, event_type: type }).then(setData).catch(() => {}), [q, type]);
  useEffect(() => { const t = setTimeout(load, 150); return () => clearTimeout(t); }, [load]);
  useEffect(() => { api.getConfig().then(setConfig).catch(() => {}); }, []);
  useEffect(() => {
    // Opening the panel counts as seeing everything in it.
    api.markNotificationsRead().then(() => window.dispatchEvent(new CustomEvent("zenith:notifications-read"))).catch(() => {});
  }, []);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const patch = async (body) => setConfig(await api.patchConfig(body));
  const muted = new Set(config?.notify_desktop_muted || []);
  const toggleMute = (t) => {
    const next = new Set(muted);
    if (next.has(t)) next.delete(t); else next.add(t);
    patch({ notify_desktop_muted: [...next] });
  };

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal notif-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="notif-title">
        <div className="notes-header">
          <span id="notif-title"><Icon name="bell" size={16} /> Notifications</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        <div className="rr-tabs">
          {[["history", "History"], ["settings", "What pops up"]].map(([k, l]) => (
            <button key={k} className={`membrowser-filter ${tab === k ? "is-on" : ""}`} onClick={() => setTab(k)}>{l}</button>
          ))}
          {data.quiet_now && <span className="mb-badge warn" style={{ marginLeft: "auto" }}>Quiet hours now</span>}
        </div>
        {tab === "history" ? (
          <>
            <div className="membrowser-tools" style={{ paddingTop: 4 }}>
              <div className="chatmgr-row">
                <input className="membrowser-search" placeholder="Search notifications…" value={q} onChange={(e) => setQ(e.target.value)} />
              </div>
              <div className="membrowser-filters">
                <button className={`membrowser-filter ${!type ? "is-on" : ""}`} onClick={() => setType("")}>All</button>
                {Object.entries(data.labels).map(([k, l]) => (
                  <button key={k} className={`membrowser-filter ${type === k ? "is-on" : ""}`} onClick={() => setType(k)}>{l}</button>
                ))}
              </div>
            </div>
            <div className="membrowser-list">
              {data.items.length === 0 && <p className="conversation-empty">Nothing here yet. Finished schedules and background tasks, digests and urgent email show up here.</p>}
              {data.items.map((n) => (
                <div key={n.id} className={`membrowser-row notif-row ${n.read_at ? "" : "is-unread"}`}>
                  <div className="membrowser-main">
                    <div className="notif-title"><strong>{n.title}</strong><em>{when(n.created_at)}</em></div>
                    {n.body && <p className="notif-body">{n.body}</p>}
                    <div className="membrowser-meta">
                      <span className="mb-badge">{data.labels[n.event_type] || n.event_type}</span>
                      {!n.desktop && <span title="Didn't pop up: muted or during quiet hours">silent</span>}
                      {n.push_status === "sent" && <span title="Also pushed to your phone">pushed</span>}
                      {n.push_status === "failed" && <span className="notif-push-failed" title={n.push_error || ""}>push failed</span>}
                      {n.event_type.startsWith("agent_run") && n.data?.id && <button className="mb-link" onClick={() => { onClose(); openTasks(n.data.id); }}>Open task</button>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {data.items.length > 0 && (
              <div className="cstate-foot"><span /><button className="wf-btn danger" onClick={async () => { await api.clearNotifications(); load(); }}>Clear history</button></div>
            )}
          </>
        ) : config && (
          <div className="notif-settings">
            {!notificationsEnabled && (
              <div className="wf-alert review"><strong>Desktop pop-ups are off.</strong><p>Everything still lands in the history.</p><div><button className="wf-btn primary" onClick={onEnableDesktop}>Turn on pop-ups</button></div></div>
            )}
            <h4>Pop up for</h4>
            {Object.entries(data.labels).map(([k, l]) => (
              <label key={k} className="notif-opt">
                <span>{l}</span>
                <button className={`switch ${!muted.has(k) ? "switch-on" : ""}`} role="switch" aria-checked={!muted.has(k)} onClick={() => toggleMute(k)}><span className="switch-thumb" /></button>
              </label>
            ))}
            <h4>Quiet hours</h4>
            <p className="wf-muted" style={{ margin: "0 0 10px" }}>No pop-ups or phone pushes in this window; the history still records everything.</p>
            <div className="notif-quiet">
              <label>From <input type="time" value={config.notify_quiet_start || ""} onChange={(e) => patch({ notify_quiet_start: e.target.value })} /></label>
              <label>To <input type="time" value={config.notify_quiet_end || ""} onChange={(e) => patch({ notify_quiet_end: e.target.value })} /></label>
              {(config.notify_quiet_start || config.notify_quiet_end) && <button className="wf-btn" onClick={() => patch({ notify_quiet_start: "", notify_quiet_end: "" })}>Off</button>}
            </div>
            <h4>Keep history for</h4>
            <div className="notif-quiet">
              <label><input type="number" min={1} max={365} value={config.notify_history_days || 30} onChange={(e) => patch({ notify_history_days: Math.max(1, Math.min(365, Number(e.target.value) || 30)) })} /> days</label>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
