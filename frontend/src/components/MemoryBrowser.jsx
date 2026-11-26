import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { confirmDialog, promptDialog } from "../lib/dialogs";
import Icon from "./Icon.jsx";
import Select from "./Select.jsx";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "pending", label: "Needs review" },
  { id: "global", label: "Everywhere" },
  { id: "project", label: "Project" },
  { id: "conversation", label: "One chat" },
  { id: "off", label: "Turned off" },
];
const SCOPE_LABEL = { global: "Everywhere", project: "This project", conversation: "This chat only" };

function ago(ts) {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** Everything Zenith remembers about you: search, edit, re-scope,
 * approve, merge, turn off, forget and export. */
export default function MemoryBrowser({ focusId, onClose, onOpenConversation }) {
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(new Set());
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [config, setConfig] = useState(null);
  const [exclusions, setExclusions] = useState("");

  const load = useCallback(async () => {
    try {
      const params = { q };
      if (filter === "pending") params.status = "pending";
      else if (["global", "project", "conversation"].includes(filter)) params.scope = filter;
      let r = await api.browseMemories(params);
      if (filter === "off") r = r.filter((m) => !m.enabled);
      setRows(r); setError("");
    } catch (e) { setError(e.message); }
  }, [q, filter]);

  useEffect(() => { const t = setTimeout(load, 150); return () => clearTimeout(t); }, [load]);
  useEffect(() => {
    api.getConfig().then((c) => { setConfig(c); setExclusions((c.memory_exclusions || []).join(", ")); }).catch(() => {});
  }, []);
  useEffect(() => {
    if (!focusId) return;
    const t = setTimeout(() => document.getElementById(`mem-${focusId}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 250);
    return () => clearTimeout(t);
  }, [focusId, rows.length]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && !editing && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, editing]);

  const patch = async (id, body) => {
    try { await api.updateMemory(id, body); await load(); } catch (e) { setError(e.message); }
  };
  const saveEdit = async () => { const id = editing; setEditing(null); if (draft.trim()) await patch(id, { content: draft.trim() }); };
  const forget = async (m) => {
    if (!(await confirmDialog({ title: "Forget this?", message: `“${m.content}”`, confirmLabel: "Forget", danger: true }))) return;
    await api.deleteMemory(m.id); setSelected((s) => { const n = new Set(s); n.delete(m.id); return n; }); load();
  };
  const merge = async () => {
    const picked = rows.filter((r) => selected.has(r.id));
    const text = await promptDialog({
      title: `Merge ${picked.length} memories`, message: "They'll be replaced by this one.",
      defaultValue: picked.map((p) => p.content).join("; "), confirmLabel: "Merge", multiline: true,
    });
    if (!text) return;
    try { await api.mergeMemories(picked.map((p) => p.id), text); setSelected(new Set()); load(); } catch (e) { setError(e.message); }
  };
  const forgetSelected = async () => {
    if (!(await confirmDialog({ title: `Forget ${selected.size} memories?`, confirmLabel: "Forget", danger: true }))) return;
    await Promise.all([...selected].map((id) => api.deleteMemory(id)));
    setSelected(new Set()); load();
  };
  const saveConfig = async (body) => { try { setConfig(await api.patchConfig(body)); } catch (e) { setError(e.message); } };

  const pendingCount = useMemo(() => rows.filter((r) => r.status === "pending").length, [rows]);

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal membrowser" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="mem-title">
        <div className="notes-header">
          <span id="mem-title"><Icon name="layers" size={16} /> Memory</span>
          <div className="membrowser-head-actions">
            <a className="wf-btn" href={api.exportMemoriesUrl()} download="zenith-memories.json"><Icon name="download" size={13} /> Export</a>
            <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
          </div>
        </div>

        <div className="membrowser-tools">
          <input className="membrowser-search" placeholder="Search what Zenith remembers…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search memories" />
          <div className="membrowser-filters" role="tablist">
            {FILTERS.map((f) => (
              <button key={f.id} role="tab" aria-selected={filter === f.id} className={`membrowser-filter ${filter === f.id ? "is-on" : ""}`} onClick={() => setFilter(f.id)}>
                {f.label}{f.id === "pending" && filter !== "pending" && pendingCount > 0 ? ` · ${pendingCount}` : ""}
              </button>
            ))}
          </div>
        </div>

        {selected.size > 0 && (
          <div className="membrowser-bulk">
            <span>{selected.size} selected</span>
            <button className="wf-btn" onClick={merge} disabled={selected.size < 2}>Merge</button>
            <button className="wf-btn danger" onClick={forgetSelected}>Forget</button>
            <button className="wf-btn" onClick={() => setSelected(new Set())}>Clear</button>
          </div>
        )}
        {error && <div className="cstate-error" style={{ margin: "0 26px 10px" }}>{error}</div>}

        <div className="membrowser-list">
          {rows.length === 0 && <p className="conversation-empty">{q || filter !== "all" ? "Nothing matches." : "Nothing remembered yet. Zenith picks up lasting facts as you chat."}</p>}
          {rows.map((m) => (
            <div key={m.id} id={`mem-${m.id}`} className={`membrowser-row ${m.status === "pending" ? "is-pending" : ""} ${m.enabled ? "" : "is-off"} ${focusId === m.id ? "is-focus" : ""}`}>
              <input type="checkbox" className="membrowser-check" checked={selected.has(m.id)} aria-label="Select"
                onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(m.id); else n.delete(m.id); return n; })} />
              <div className="membrowser-main">
                {editing === m.id ? (
                  <textarea autoFocus rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={saveEdit}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveEdit(); } if (e.key === "Escape") setEditing(null); }} />
                ) : (
                  <button className="membrowser-text" onClick={() => { setEditing(m.id); setDraft(m.content); }} title="Click to edit">{m.content}</button>
                )}
                <div className="membrowser-meta">
                  {m.status === "pending" && <span className="mb-badge warn">Needs review{m.confidence != null && m.confidence < 0.6 ? " · unsure" : ""}</span>}
                  <span className="mb-badge">{SCOPE_LABEL[m.scope] || "Everywhere"}</span>
                  {m.confidence != null && <span title="How sure Zenith was when it saved this">{Math.round(m.confidence * 100)}% sure</span>}
                  <span>used {m.use_count || 0}× · {ago(m.last_used_at)}</span>
                  {m.source_conversation_id && (
                    <button className="mb-link" onClick={() => onOpenConversation?.(m.source_conversation_id, m.source_message_id)} title="Open the chat this came from">
                      from “{m.source_title || "a chat"}”
                    </button>
                  )}
                  <span>saved {ago(m.created_at)}</span>
                </div>
              </div>
              <div className="membrowser-actions">
                {m.status === "pending" && <button className="wf-btn primary" onClick={() => patch(m.id, { status: "active" })}>Keep</button>}
                <Select value={m.scope || "global"} onChange={(e) => patch(m.id, { scope: e.target.value, conversation_id: m.scope_conversation_id || m.source_conversation_id, project_id: m.project_id })} aria-label="Where this applies">
                  <option value="global">Everywhere</option>
                  <option value="project" disabled={!m.project_id}>This project</option>
                  <option value="conversation" disabled={!m.source_conversation_id && !m.scope_conversation_id}>This chat only</option>
                </Select>
                <button className={`switch ${m.enabled ? "switch-on" : ""}`} role="switch" aria-checked={!!m.enabled} aria-label="Use this memory" onClick={() => patch(m.id, { enabled: !m.enabled })}><span className="switch-thumb" /></button>
                <button className="cstate-del" onClick={() => forget(m)} aria-label="Forget" title="Forget"><Icon name="trash" size={13} /></button>
              </div>
            </div>
          ))}
        </div>

        {config && (
          <div className="membrowser-foot">
            <label className="membrowser-opt">
              <button className={`switch ${config.memory_require_approval ? "switch-on" : ""}`} role="switch" aria-checked={!!config.memory_require_approval}
                onClick={() => saveConfig({ memory_require_approval: !config.memory_require_approval })}><span className="switch-thumb" /></button>
              <span>Ask before saving anything <em>(uncertain and private facts always ask)</em></span>
            </label>
            <label className="membrowser-excl">
              <span>Never remember</span>
              <input value={exclusions} placeholder="e.g. salary, password, my ex" onChange={(e) => setExclusions(e.target.value)}
                onBlur={() => saveConfig({ memory_exclusions: exclusions.split(",").map((x) => x.trim()).filter(Boolean) })} />
            </label>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
