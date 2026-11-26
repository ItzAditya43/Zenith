import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const GROUPS = [
  ["duplicate_memory", "Duplicate memories"],
  ["stale_memory", "Memories you haven't used in months"],
  ["orphan_source", "Index entries whose source is gone"],
  ["duplicate_document", "Documents indexed twice"],
  ["changed_file", "Watched files changed since indexing"],
];

/** Review-then-apply cleanup of memories and the retrieval index. Every
 * applied batch can be undone from the history below. */
export default function CleanupPanel({ onClose }) {
  const [data, setData] = useState(null);
  const [pick, setPick] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const load = () => api.cleanupScan().then((d) => { setData(d); setPick(new Set(d.proposals.filter((p) => p.kind !== "stale_memory").map((p) => p.id))); }).catch((e) => setMsg(e.message));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const apply = async () => {
    setBusy(true);
    try { const r = await api.cleanupApply([...pick]); setMsg(`Done: ${r.applied.length} change${r.applied.length === 1 ? "" : "s"}. You can undo it below.`); await load(); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };
  const undo = async (id) => {
    try { const r = await api.cleanupUndo(id); setMsg(`Undone — restored ${r.restored} item${r.restored === 1 ? "" : "s"}.`); await load(); } catch (e) { setMsg(e.message); }
  };

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal cleanup-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="cleanup-title">
        <div className="notes-header">
          <span id="cleanup-title"><Icon name="wrench" size={16} /> Knowledge cleanup</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        <div className="membrowser-list" style={{ paddingTop: 14 }}>
          <p className="cstate-lead" style={{ margin: "0 0 6px" }}>
            Things that could make answers worse: repeats, leftovers from deleted files and chats, and memories nobody uses.
            Nothing changes until you apply, and every cleanup can be undone.
          </p>
          {msg && <div className="cstate-error">{msg}</div>}
          {!data ? <p className="conversation-empty">Checking…</p> : data.proposals.length === 0 ? (
            <p className="conversation-empty">All tidy — nothing to clean up.</p>
          ) : GROUPS.map(([kind, label]) => {
            const items = data.proposals.filter((p) => p.kind === kind);
            if (!items.length) return null;
            return (
              <section key={kind} className="cleanup-group">
                <h4>{label} · {items.length}</h4>
                {items.map((p) => (
                  <label key={p.id} className="membrowser-row cleanup-row">
                    <input type="checkbox" className="membrowser-check" checked={pick.has(p.id)}
                      onChange={(e) => setPick((s) => { const n = new Set(s); if (e.target.checked) n.add(p.id); else n.delete(p.id); return n; })} />
                    <div className="membrowser-main">
                      <div className="membrowser-text" style={{ cursor: "default" }}>{p.title}</div>
                      <div className="membrowser-meta"><span className="mb-badge">{p.action}</span><span>{p.detail}</span></div>
                    </div>
                  </label>
                ))}
              </section>
            );
          })}
          {data?.history?.length > 0 && (
            <section className="cleanup-group">
              <h4>Recent cleanups</h4>
              {data.history.map((h) => (
                <div key={h.id} className="cleanup-hist">
                  <span>{new Date(h.created_at * 1000).toLocaleString()} · {h.applied.length} change{h.applied.length === 1 ? "" : "s"}</span>
                  {h.undone_at ? <em>undone</em> : <button className="wf-btn" onClick={() => undo(h.id)}>Undo</button>}
                </div>
              ))}
            </section>
          )}
        </div>
        <div className="cstate-foot">
          <span className="wf-muted" style={{ margin: 0 }}>{pick.size} selected</span>
          <button className="wf-btn primary" onClick={apply} disabled={!pick.size || busy}>{busy ? "Applying…" : "Apply selected"}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
