import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

/** Asks for a quick action's {{fields}} before it's inserted or sent. */
export default function TemplateFillDialog({ action, onCancel, onDone }) {
  const [values, setValues] = useState(() => Object.fromEntries(action.fields.map((f) => [f.name, f.default || ""])));
  const [error, setError] = useState("");
  const first = useRef(null);
  useEffect(() => { first.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const submit = async (e) => {
    e.preventDefault();
    try { const { text } = await api.renderTemplate(action.prompt_template, values); onDone(text); }
    catch (err) { setError(err.message); }
  };

  return createPortal(
    <div className="notes-overlay" onClick={onCancel}>
      <form className="notes-modal tfill" onClick={(e) => e.stopPropagation()} onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="tfill-title">
        <div className="notes-header">
          <span id="tfill-title"><Icon name="bolt" size={16} /> {action.name}</span>
          <button type="button" className="icon-btn" onClick={onCancel} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        <div className="tfill-body">
          {action.fields.map((f, i) => (
            <label key={f.name}>
              <span>{f.name}</span>
              <textarea ref={i === 0 ? first : undefined} rows={f.name.length > 12 ? 3 : 1} value={values[f.name]} placeholder={f.default || ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form.requestSubmit(); } }} />
            </label>
          ))}
          {error && <div className="cstate-error">{error}</div>}
        </div>
        <div className="cstate-foot">
          <span className="wf-muted" style={{ margin: 0 }}>{action.auto_send ? "Sends right away." : "Goes into the message box for you to check."}</span>
          <button type="submit" className="wf-btn primary">{action.auto_send ? "Send" : "Insert"}</button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
