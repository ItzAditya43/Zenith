import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { confirmDialog } from "../lib/dialogs";
import DiffView from "./DiffView.jsx";
import Icon from "./Icon.jsx";

const STATUS = { executed: "ran", done: "ran", denied: "denied", rejected: "denied", pending: "waiting", reverted: "undone", failed: "failed" };

/** Everything one agent run did, in one place: changed files with their
 * diffs, commands and checks with output, and the full tool timeline.
 * Accept marks it reviewed, Undo all restores every file it edited, and
 * Continue hands the conversation back for a follow-up. */
export default function RunReview({ runId, onClose, onContinue, onReverted }) {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("files");
  const [openFile, setOpenFile] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = () => api.reviewRun(runId).then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [runId]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const accept = async () => {
    if (data?.background?.id) await api.markBackgroundReviewed(data.background.id).catch(() => {});
    onClose();
  };
  const undoAll = async () => {
    if (!(await confirmDialog({ title: "Undo every file change from this run?", message: "Files go back to how they were before the run. Commands that already ran can't be undone.", confirmLabel: "Undo all", danger: true }))) return;
    setBusy("undo");
    try { await api.revertRun(runId); await load(); onReverted?.(); } catch (e) { setError(e.message); } finally { setBusy(""); }
  };

  const c = data?.counts;
  const file = data?.files?.[openFile];

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal runreview" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="rr-title">
        <div className="notes-header">
          <span id="rr-title"><Icon name="check-circle" size={16} /> Review run</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        {error && <div className="cstate-error" style={{ margin: "12px 26px 0" }}>{error}</div>}
        {!data ? <p className="conversation-empty">Loading…</p> : (
          <>
            <div className="rr-summary">
              <div className="rr-prompt"><span>Asked</span><p>{data.prompt || "—"}</p></div>
              <div className="rr-stats">
                <b>{c.files}</b><span>file{c.files === 1 ? "" : "s"} changed</span>
                <b>{data.commands.length}</b><span>command{data.commands.length === 1 ? "" : "s"}</span>
                <b>{data.activity.length}</b><span>step{data.activity.length === 1 ? "" : "s"}</span>
                {c.denied > 0 && <><b className="warn">{c.denied}</b><span>denied</span></>}
                {c.pending > 0 && <><b className="warn">{c.pending}</b><span>waiting</span></>}
              </div>
            </div>
            <div className="rr-tabs" role="tablist">
              {[["files", "Changes"], ["commands", "Commands & checks"], ["activity", "Timeline"], ["reply", "Reply"]].map(([k, label]) => (
                <button key={k} role="tab" aria-selected={tab === k} className={`membrowser-filter ${tab === k ? "is-on" : ""}`} onClick={() => setTab(k)}>{label}</button>
              ))}
            </div>
            <div className="rr-body">
              {tab === "files" && (data.files.length === 0 ? <p className="wf-muted">This run didn't change any files.</p> : (
                <div className="rr-files">
                  <ul className="rr-filelist">
                    {data.files.map((f, i) => (
                      <li key={f.path}><button className={i === openFile ? "is-on" : ""} onClick={() => setOpenFile(i)}>
                        <Icon name="file-text" size={13} /><span>{f.path}</span>
                        <em className={f.reverted ? "warn" : f.applied ? "ok" : ""}>{f.reverted ? "undone" : f.applied ? "applied" : "not applied"}</em>
                      </button></li>
                    ))}
                  </ul>
                  <div className="rr-diff">
                    {file?.diffs.length ? file.diffs.map((d, i) => <DiffView key={i} diff={d} />) : <p className="wf-muted">No diff recorded for this file.</p>}
                  </div>
                </div>
              ))}
              {tab === "commands" && (data.commands.length === 0 ? <p className="wf-muted">No commands ran.</p> : data.commands.map((cmd) => (
                <div key={cmd.id} className="rr-cmd">
                  <div className="rr-cmd-head"><code>{cmd.command}</code>{cmd.is_check && <span className="mb-badge">check</span>}<em>{STATUS[cmd.status] || cmd.status}</em></div>
                  {cmd.result && <pre>{cmd.result}</pre>}
                </div>
              )))}
              {tab === "activity" && (
                <ol className="wf-steps rr-timeline">
                  {data.activity.map((a) => (
                    <li key={a.id} className={`k-${a.status === "executed" ? "done" : a.status === "pending" ? "wait" : a.status === "denied" ? "error" : "start"}`}>
                      <i /><strong>{a.tool}</strong>&nbsp;<span className="rr-args">{JSON.stringify(a.args).slice(0, 140)}</span><em>{STATUS[a.status] || a.status}</em>
                    </li>
                  ))}
                </ol>
              )}
              {tab === "reply" && <pre className="wf-out final">{data.reply || "No reply was saved."}</pre>}
            </div>
            <div className="cstate-foot">
              <button className="wf-btn danger" onClick={undoAll} disabled={!!busy || c.edits_applied === 0}>{busy === "undo" ? "Undoing…" : "Undo all changes"}</button>
              <div>
                <button className="wf-btn" onClick={() => { onClose(); onContinue?.(); }}>Continue in chat</button>
                <button className="wf-btn primary" onClick={accept}>{data.background?.reviewed_at ? "Done" : "Accept"}</button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
