import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { openRunReview } from "../lib/uiEvents.js";
import Icon from "./Icon.jsx";

const LABEL = { queued: "Queued", running: "Running", waiting: "Needs your OK", done: "Done", failed: "Failed", cancelled: "Cancelled", interrupted: "Interrupted" };
const ACTIVE = ["queued", "running", "waiting"];

function when(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function describe(ev) {
  switch (ev.type) {
    case "route": return `Using ${ev.model}`;
    case "tool_call": return `${ev.tool} ${JSON.stringify(ev.args || {}).slice(0, 90)}`;
    case "tool_pending": return `Waiting for approval: ${ev.tool}`;
    case "tool_result": return `${ev.tool || "tool"} finished`;
    case "tool_denied": return "Step denied";
    case "done": return "Finished";
    case "error": return `Error: ${ev.message}`;
    case "cancelled": return "Cancelled";
    default: return ev.type.replace(/_/g, " ");
  }
}

/** Agent tasks that run in the background: queue one for the current
 * chat, watch it live, approve steps, cancel, and review what it did. */
export default function TasksPanel({ conversationId, conversationTitle, agentAvailable, focusId, onClose, onOpenConversation }) {
  const [runs, setRuns] = useState([]);
  const [sel, setSel] = useState(focusId);
  const [detail, setDetail] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");

  const loadList = useCallback(() => api.listBackgroundRuns().then(setRuns).catch((e) => setError(e.message)), []);
  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => {
    if (!sel) return;
    let stop = false;
    const tick = async () => {
      try { const d = await api.getBackgroundRun(sel); if (!stop) setDetail(d); if (ACTIVE.includes(d.status) && !stop) setTimeout(tick, 1500); else loadList(); } catch { /* gone */ }
    };
    tick();
    return () => { stop = true; };
  }, [sel, loadList]);
  useEffect(() => {
    if (!runs.some((r) => ACTIVE.includes(r.status))) return;
    const t = setInterval(loadList, 3000);
    return () => clearInterval(t);
  }, [runs, loadList]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const queue = async () => {
    if (!prompt.trim() || !conversationId) return;
    setError("");
    try { const r = await api.queueBackgroundRun(conversationId, prompt.trim()); setPrompt(""); await loadList(); setSel(r.id); }
    catch (e) { setError(e.message); }
  };
  const pendingIds = (d) => {
    const resolved = new Set(d.log.filter((e) => e.type === "tool_result" || e.type === "tool_denied").map((e) => e.id));
    return d.log.filter((e) => e.type === "tool_pending" && !resolved.has(e.id));
  };
  const decide = async (id, ok) => { try { if (ok) await api.approveToolCall(id); else await api.denyToolCall(id); } catch (e) { setError(e.message); } };

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal tasks-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="tasks-title">
        <div className="notes-header">
          <span id="tasks-title"><Icon name="clock" size={16} /> Background tasks</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        <div className="tasks-new">
          {!agentAvailable ? (
            <p className="wf-muted">Turn on agent tools in Settings → Agent tools to run tasks in the background.</p>
          ) : !conversationId ? (
            <p className="wf-muted">Open a chat first; the task runs in that chat and its folder.</p>
          ) : (
            <>
              <textarea rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={`What should the agent do in “${conversationTitle || "this chat"}”? It keeps going if you close the window.`}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) queue(); }} />
              <button className="wf-btn primary" onClick={queue} disabled={!prompt.trim()}>Queue task</button>
            </>
          )}
        </div>
        {error && <div className="cstate-error" style={{ margin: "0 26px 10px" }}>{error}</div>}
        <div className="tasks-body">
          <ul className="tasks-list">
            {runs.length === 0 && <li className="wf-muted" style={{ padding: 12 }}>No tasks yet.</li>}
            {runs.map((r) => (
              <li key={r.id}>
                <button className={sel === r.id ? "is-on" : ""} onClick={() => setSel(r.id)}>
                  <span className={`task-dot s-${r.status}`} />
                  <span className="task-text"><strong>{r.prompt}</strong><em>{LABEL[r.status]} · {when(r.created_at)}{r.status === "done" && !r.reviewed_at ? " · not reviewed" : ""}</em></span>
                </button>
              </li>
            ))}
          </ul>
          <div className="tasks-detail">
            {!detail || !sel ? <p className="wf-muted">Pick a task to see what it's doing.</p> : (
              <>
                <div className="tasks-detail-head">
                  <span className={`mb-badge ${detail.status === "waiting" ? "warn" : ""}`}>{LABEL[detail.status]}</span>
                  {detail.model && <span className="wf-muted" style={{ margin: 0 }}>{detail.model}</span>}
                  <div className="tasks-detail-actions">
                    {ACTIVE.includes(detail.status) && <button className="wf-btn danger" onClick={async () => { await api.cancelBackgroundRun(detail.id).catch(() => {}); loadList(); }}>Cancel</button>}
                    {detail.run_id && <button className="wf-btn primary" onClick={() => openRunReview(detail.run_id)}>Review changes</button>}
                    <button className="wf-btn" onClick={() => onOpenConversation(detail.conversation_id)}>Open chat</button>
                  </div>
                </div>
                <p className="tasks-prompt">{detail.prompt}</p>
                {pendingIds(detail).map((p) => (
                  <div key={p.id} className="wf-alert review">
                    <strong>Approve {p.tool}?</strong>
                    <p>{p.diff || JSON.stringify(p.args, null, 2)}</p>
                    <div><button className="wf-btn primary" onClick={() => decide(p.id, true)}>Approve</button><button className="wf-btn" onClick={() => decide(p.id, false)}>Deny</button></div>
                  </div>
                ))}
                {detail.error && <div className="wf-alert error">{detail.error}</div>}
                <ol className="wf-steps">
                  {detail.log.map((ev, i) => (
                    <li key={i} className={`k-${ev.type === "tool_result" || ev.type === "done" ? "done" : ev.type === "tool_pending" ? "wait" : ev.type === "error" || ev.type === "tool_denied" ? "error" : "start"}`}><i />{describe(ev)}</li>
                  ))}
                </ol>
                {detail.summary && <><h4 className="tasks-h4">Result</h4><pre className="wf-out final">{detail.summary}</pre></>}
              </>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
