import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { confirmDialog } from "../lib/dialogs";
import Icon from "./Icon.jsx";

/** What Zenith carries forward from the older part of a long chat:
 * goals, decisions, constraints, facts, files, open questions and next
 * actions, each linked to the messages it came from. Everything here is
 * editable; pinned items survive regeneration and edits to the chat. */
export default function ConversationStatePanel({ conversationId, onClose }) {
  const [data, setData] = useState(null);
  const [state, setState] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [adding, setAdding] = useState({});

  const load = () =>
    api.getConversationState(conversationId).then((d) => { setData(d); setState(d.state); setDirty(false); }).catch((e) => setError(e.message));
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [conversationId]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const edit = (key, idx, patch) => {
    setState((s) => ({ ...s, [key]: s[key].map((it, i) => (i === idx ? { ...it, ...patch } : it)) }));
    setDirty(true);
  };
  const remove = (key, idx) => { setState((s) => ({ ...s, [key]: s[key].filter((_, i) => i !== idx) })); setDirty(true); };
  const add = (key) => {
    const text = (adding[key] || "").trim();
    if (!text) return;
    setState((s) => ({ ...s, [key]: [...(s[key] || []), { text, sources: [], pinned: true }] }));
    setAdding((a) => ({ ...a, [key]: "" }));
    setDirty(true);
  };
  const save = async () => {
    setBusy("save"); setError("");
    try { const d = await api.saveConversationState(conversationId, state); setData(d); setState(d.state); setDirty(false); }
    catch (e) { setError(e.message); } finally { setBusy(""); }
  };
  const regenerate = async () => {
    if (dirty && !(await confirmDialog({ title: "Discard unsaved edits?", message: "Regenerating rebuilds from the messages. Pinned items you saved are kept.", confirmLabel: "Regenerate" }))) return;
    setBusy("regen"); setError("");
    try {
      const d = await api.regenerateConversationState(conversationId);
      setData(d); setState(d.state); setDirty(false);
      if (!d.regenerated) setError("Nothing new to compact yet, or no local model was available.");
    } catch (e) { setError(e.message); } finally { setBusy(""); }
  };
  const clearAll = async () => {
    if (!(await confirmDialog({ title: "Clear the conversation state?", message: "Pinned items are removed too. It rebuilds automatically as the chat grows.", confirmLabel: "Clear", danger: true }))) return;
    await api.clearConversationState(conversationId);
    load();
  };
  const jump = (id) => {
    const el = document.getElementById(`msg-${id}`);
    if (!el) return;
    onClose();
    setTimeout(() => { el.scrollIntoView({ behavior: "smooth", block: "center" }); el.classList.add("msg-flash"); setTimeout(() => el.classList.remove("msg-flash"), 1600); }, 60);
  };

  const total = state ? Object.values(state).reduce((n, v) => n + v.length, 0) : 0;

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal cstate-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="cstate-title">
        <div className="notes-header">
          <span id="cstate-title"><Icon name="layers" size={16} /> Conversation state</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        <div className="cstate-body">
          {data && (
            <p className="cstate-lead">
              The model sees the last {data.window} messages word for word. {data.dropped_count > 0
                ? <>The {data.dropped_count} older ones are carried forward as the notes below{data.current ? "" : " (out of date after an edit — regenerate to refresh)"}.</>
                : <>This chat still fits, so nothing has been compacted yet{total ? "; your pinned notes are ready for when it does" : ""}.</>}
              {!data.enabled && " Automatic compaction is off in Settings."}
            </p>
          )}
          {error && <div className="cstate-error">{error}</div>}
          {data && state && data.sections.map(({ key, title }) => (
            <section key={key} className="cstate-section">
              <h4>{title}</h4>
              {(state[key] || []).map((it, i) => (
                <div className={`cstate-item ${it.pinned ? "is-pinned" : ""}`} key={`${key}-${i}`}>
                  <textarea rows={1} value={it.text} onChange={(e) => edit(key, i, { text: e.target.value })} aria-label={`${title} item`} />
                  <div className="cstate-item-meta">
                    {it.sources?.map((id, n) => (
                      <button key={id} className="cstate-src" onClick={() => jump(id)} title="Show the message this came from">#{n + 1}</button>
                    ))}
                    <button className={`cstate-pin ${it.pinned ? "is-on" : ""}`} onClick={() => edit(key, i, { pinned: !it.pinned })} title={it.pinned ? "Unpin" : "Pin: keep this through regeneration and edits"} aria-pressed={it.pinned}>
                      <Icon name="target" size={12} />
                    </button>
                    <button className="cstate-del" onClick={() => remove(key, i)} title="Remove" aria-label="Remove"><Icon name="x" size={12} /></button>
                  </div>
                </div>
              ))}
              <div className="cstate-add">
                <input value={adding[key] || ""} placeholder={`Add to ${title.toLowerCase()}…`} onChange={(e) => setAdding((a) => ({ ...a, [key]: e.target.value }))} onKeyDown={(e) => e.key === "Enter" && add(key)} />
              </div>
            </section>
          ))}
        </div>
        <div className="cstate-foot">
          <button className="wf-btn danger" onClick={clearAll} disabled={!!busy}>Clear</button>
          <div>
            <button className="wf-btn" onClick={regenerate} disabled={!!busy}>{busy === "regen" ? "Regenerating…" : "Regenerate"}</button>
            <button className="wf-btn primary" onClick={save} disabled={!dirty || !!busy}>{busy === "save" ? "Saving…" : "Save"}</button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
