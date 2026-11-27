import { useEffect, useState } from "react";
import { api } from "../../lib/api";

const when = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString() : "—");

function Side({ label, mem, suggested }) {
  return (
    <div className={`conflict-side ${suggested ? "is-suggested" : ""}`}>
      <span className="conflict-side-label">{label}{suggested ? " · suggested" : ""}</span>
      <p>{mem.content}</p>
      <span className="setting-hint">
        Saved {when(mem.created_at)}
        {mem.updated_at && mem.updated_at - mem.created_at > 60 ? ` · changed ${when(mem.updated_at)}` : ""}
        {mem.source_title ? ` · from “${mem.source_title}”` : " · added by hand or imported"}
      </span>
    </div>
  );
}

function Conflict({ c, onResolve }) {
  const [merging, setMerging] = useState(false);
  const [text, setText] = useState(`${c.memory_a.content}; ${c.memory_b.content}`);
  const [err, setErr] = useState("");
  const act = async (action, t = "") => {
    setErr("");
    try {
      await onResolve(c.id, action, t);
    } catch (e) {
      setErr(e.message || "Couldn't resolve that.");
    }
  };
  const s = c.suggestion?.action;
  return (
    <li className="conflict-card">
      <span className="setting-hint">{c.reason}</span>
      <div className="conflict-sides">
        <Side label="A" mem={c.memory_a} suggested={s === "keep_a"} />
        <Side label="B" mem={c.memory_b} suggested={s === "keep_b"} />
      </div>
      {c.suggestion?.why && <span className="setting-hint">{c.suggestion.why}</span>}
      {merging ? (
        <div className="settings-row">
          <input className="settings-input" value={text} onChange={(e) => setText(e.target.value)} aria-label="Combined memory" />
          <button className="settings-btn-primary" onClick={() => act("merge", text)}>Save merged</button>
          <button className="text-btn" onClick={() => setMerging(false)}>Cancel</button>
        </div>
      ) : (
        <div className="settings-row" style={{ flexWrap: "wrap", gap: "0.4rem" }}>
          <button className="settings-btn-secondary" onClick={() => act("keep_a")}>Keep A</button>
          <button className="settings-btn-secondary" onClick={() => act("keep_b")}>Keep B</button>
          <button className="settings-btn-secondary" onClick={() => act("keep_both")}>Both are right</button>
          <button className="settings-btn-secondary" onClick={() => setMerging(true)}>Merge…</button>
          <button className="text-btn" onClick={() => act("dismiss")}>Dismiss</button>
        </div>
      )}
      {err && <span className="settings-error">{err}</span>}
    </li>
  );
}

/** Memory contradictions with evidence, a suggestion, and undo for recent decisions.
 * "Keep" turns the other memory off rather than deleting it. */
export default function ConflictReview({ conflicts, onResolve }) {
  const [resolved, setResolved] = useState([]);
  const load = () => api.resolvedMemoryConflicts().then(setResolved).catch(() => {});
  useEffect(() => { load(); }, [conflicts.length]);
  const LABEL = { keep_a: "kept A", keep_b: "kept B", keep_both: "kept both", merge: "merged", dismiss: "dismissed" };
  const undo = async (id) => {
    await api.undoMemoryConflict(id);
    load();
    window.dispatchEvent(new CustomEvent("zenith:memory-conflicts-changed"));
  };
  if (!conflicts.length && !resolved.length) return null;
  return (
    <div style={{ marginTop: "1rem" }}>
      {conflicts.length > 0 && (
        <>
          <strong className="setting-label">
            {conflicts.length} possible contradiction{conflicts.length === 1 ? "" : "s"}
          </strong>
          <ul className="conflict-list">
            {conflicts.map((c) => <Conflict key={c.id} c={c} onResolve={async (...a) => { await onResolve(...a); load(); }} />)}
          </ul>
        </>
      )}
      {resolved.length > 0 && (
        <details className="conflict-history">
          <summary>Recently resolved ({resolved.length})</summary>
          <ul>
            {resolved.map((c) => (
              <li key={c.id}>
                {LABEL[c.resolution] || c.resolution}: “{c.memory_a.content}” / “{c.memory_b.content}”
                <button className="text-btn" onClick={() => undo(c.id)}>Undo</button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
