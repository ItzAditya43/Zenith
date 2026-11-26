import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const LABEL = { key: "[key or token]", email: "[email address]", phone: "[phone number]", ip: "[ip address]", path: "[home-folder path]" };

function applyRedactions(text, redact) {
  let out = text;
  for (const r of [...redact].sort((a, b) => b.text.length - a.text.length)) {
    if (r.text) out = out.split(r.text).join(r.replacement || LABEL[r.kind] || "[redacted]");
  }
  return out;
}

/** Share or export a redacted copy: see what looks sensitive, choose what
 * to hide and which messages to leave out, preview the exact result. */
export default function ShareDialog({ conversationId, title, existingToken, onClose, onShared, onRevoked }) {
  const [data, setData] = useState(null);
  const [off, setOff] = useState(new Set()); // findings NOT to redact
  const [custom, setCustom] = useState([]);
  const [customText, setCustomText] = useState("");
  const [exclude, setExclude] = useState(new Set());
  const [attachments, setAttachments] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { api.sharePreview(conversationId).then(setData).catch((e) => setError(e.message)); }, [conversationId]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const redact = useMemo(() => [
    ...(data?.findings || []).filter((f) => !off.has(f.kind + f.text)).map((f) => ({ kind: f.kind, text: f.text })),
    ...custom.map((t) => ({ text: t, replacement: "[redacted]" })),
  ], [data, off, custom]);
  const body = { redact, exclude_message_ids: [...exclude], include_attachments: attachments };
  const kept = (data?.messages || []).filter((m) => !exclude.has(m.id));

  const share = async () => {
    setBusy(true); setError("");
    try {
      const { token } = await api.shareSnapshot(conversationId, body);
      const url = api.shareUrl(token);
      try { await navigator.clipboard.writeText(url); } catch { /* shown below anyway */ }
      onShared(token, url);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const download = async () => {
    const blob = await api.shareExport(conversationId, body);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(title || "conversation").replace(/[^\w]+/g, "-").toLowerCase()}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal share-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="share-title">
        <div className="notes-header">
          <span id="share-title"><Icon name="share" size={16} /> Share a copy</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        {!data ? <p className="conversation-empty">{error || "Checking the chat…"}</p> : (
          <div className="share-body">
            <aside className="share-side">
              {existingToken && (
                <div className="wf-alert review">
                  <strong>This chat has a live link.</strong>
                  <p>Sharing again replaces it with a new copy.</p>
                  <div><button className="wf-btn danger" onClick={onRevoked}>Turn off the link</button></div>
                </div>
              )}
              <h4>Hide before sharing</h4>
              {data.findings.length === 0 && <p className="wf-muted">Nothing that looks like an email, phone number, key, IP address or home folder.</p>}
              {data.findings.map((f) => {
                const k = f.kind + f.text;
                return (
                  <label key={k} className="share-find">
                    <input type="checkbox" checked={!off.has(k)} onChange={(e) => setOff((s) => { const n = new Set(s); if (e.target.checked) n.delete(k); else n.add(k); return n; })} />
                    <span><em>{f.label}</em><code>{f.text}</code>{f.count > 1 && <small>×{f.count}</small>}</span>
                  </label>
                );
              })}
              <div className="share-custom">
                <input value={customText} placeholder="Hide other text (a name, a project…)" onChange={(e) => setCustomText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && customText.trim()) { setCustom((c) => [...c, customText.trim()]); setCustomText(""); } }} />
                {custom.map((t) => <span key={t} className="mb-badge">{t} <button onClick={() => setCustom((c) => c.filter((x) => x !== t))} aria-label={`Stop hiding ${t}`}>×</button></span>)}
              </div>
              <label className="share-opt"><input type="checkbox" checked={attachments} onChange={(e) => setAttachments(e.target.checked)} /> Include attachment names (never the files)</label>
              <p className="wf-muted">The link shows this copy only. Messages you add later don't appear on it.</p>
            </aside>
            <div className="share-preview">
              <h4>Preview · {kept.length} of {data.messages.length} messages</h4>
              {data.messages.map((m) => (
                <div key={m.id} className={`share-msg role-${m.role} ${exclude.has(m.id) ? "is-out" : ""}`}>
                  <label><input type="checkbox" checked={!exclude.has(m.id)} onChange={(e) => setExclude((s) => { const n = new Set(s); if (e.target.checked) n.delete(m.id); else n.add(m.id); return n; })} /> {m.role === "user" ? "You" : "Assistant"}</label>
                  <p>{applyRedactions(m.content, redact)}</p>
                  {attachments && m.attachments?.length > 0 && <small>Attachments: {m.attachments.map((n) => applyRedactions(n, redact)).join(", ")}</small>}
                </div>
              ))}
            </div>
          </div>
        )}
        {error && data && <div className="cstate-error" style={{ margin: "0 26px 10px" }}>{error}</div>}
        <div className="cstate-foot">
          <button className="wf-btn" onClick={download} disabled={!data || !kept.length}><Icon name="download" size={13} /> Download Markdown</button>
          <button className="wf-btn primary" onClick={share} disabled={!data || !kept.length || busy}>{busy ? "Creating…" : "Create link & copy"}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
