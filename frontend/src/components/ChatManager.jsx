import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { confirmDialog, promptDialog } from "../lib/dialogs";
import Icon from "./Icon.jsx";
import Select from "./Select.jsx";

const SHOW = [
  { id: "active", label: "Active" },
  { id: "pinned", label: "Pinned" },
  { id: "archived", label: "Archived" },
  { id: "all", label: "All" },
];

function when(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" }) : "";
}

/** Organise chats in bulk: filter by text, tag and state; save filters;
 * pin, tag, archive or delete many at once. */
export default function ChatManager({ initialShow = "active", onClose, onChanged, onOpen }) {
  const [convs, setConvs] = useState([]);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [show, setShow] = useState(initialShow);
  const [sel, setSel] = useState(new Set());
  const [saved, setSaved] = useState([]);
  const [error, setError] = useState("");

  const load = () => api.listConversations().then(setConvs).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api.getConfig().then((c) => setSaved(c.saved_chat_filters || [])).catch(() => {});
  }, []);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const tags = useMemo(() => [...new Set(convs.flatMap((c) => c.tags || []))].sort(), [convs]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return convs.filter((c) => {
      if (show === "active" && c.archived) return false;
      if (show === "archived" && !c.archived) return false;
      if (show === "pinned" && !c.pinned) return false;
      if (tag && !(c.tags || []).includes(tag)) return false;
      return !needle || (c.title || "").toLowerCase().includes(needle);
    });
  }, [convs, q, tag, show]);
  const allSelected = rows.length > 0 && rows.every((r) => sel.has(r.id));

  const run = async (action, extra = null) => {
    const ids = [...sel];
    if (!ids.length) return;
    if (action === "delete" && !(await confirmDialog({ title: `Delete ${ids.length} chat${ids.length === 1 ? "" : "s"}?`, message: "Messages and attachments are removed for good. Archive instead if you might want them later.", confirmLabel: "Delete", danger: true }))) return;
    let t = extra;
    if ((action === "tag" || action === "untag") && !t) {
      t = await promptDialog({ title: action === "tag" ? "Add a tag" : "Remove a tag", placeholder: "e.g. work", confirmLabel: action === "tag" ? "Add" : "Remove" });
      if (!t) return;
    }
    try { await api.bulkConversations(ids, action, t); setSel(new Set()); await load(); onChanged?.(); } catch (e) { setError(e.message); }
  };
  const saveFilter = async () => {
    const name = await promptDialog({ title: "Save this filter", placeholder: "e.g. Work chats", confirmLabel: "Save" });
    if (!name) return;
    const next = [...saved.filter((f) => f.name !== name), { name, q, tag, show }];
    setSaved(next);
    api.patchConfig({ saved_chat_filters: next }).catch((e) => setError(e.message));
  };
  const dropFilter = (name) => {
    const next = saved.filter((f) => f.name !== name);
    setSaved(next);
    api.patchConfig({ saved_chat_filters: next }).catch(() => {});
  };

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal chatmgr" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="chatmgr-title">
        <div className="notes-header">
          <span id="chatmgr-title"><Icon name="layers" size={16} /> Manage chats</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        <div className="membrowser-tools">
          <div className="chatmgr-row">
            <input className="membrowser-search" placeholder="Filter by title…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter chats" />
            <Select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Tag">
              <option value="">Any tag</option>
              {tags.map((t) => <option key={t} value={t}>#{t}</option>)}
            </Select>
          </div>
          <div className="membrowser-filters">
            {SHOW.map((s) => (
              <button key={s.id} className={`membrowser-filter ${show === s.id ? "is-on" : ""}`} onClick={() => setShow(s.id)}>{s.label}</button>
            ))}
            <span className="chatmgr-sep" />
            {saved.map((f) => (
              <span key={f.name} className="chatmgr-saved">
                <button className="membrowser-filter" onClick={() => { setQ(f.q || ""); setTag(f.tag || ""); setShow(f.show || "active"); }}>★ {f.name}</button>
                <button className="chatmgr-x" onClick={() => dropFilter(f.name)} aria-label={`Remove saved filter ${f.name}`}><Icon name="x" size={10} /></button>
              </span>
            ))}
            <button className="membrowser-filter" onClick={saveFilter} title="Save the current filter">+ Save filter</button>
          </div>
        </div>
        <div className="membrowser-bulk chatmgr-bulk">
          <label className="chatmgr-all"><input type="checkbox" checked={allSelected} onChange={(e) => setSel(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())} /> {sel.size ? `${sel.size} selected` : `${rows.length} chat${rows.length === 1 ? "" : "s"}`}</label>
          <button className="wf-btn" disabled={!sel.size} onClick={() => run("pin")}>Pin</button>
          <button className="wf-btn" disabled={!sel.size} onClick={() => run("unpin")}>Unpin</button>
          <button className="wf-btn" disabled={!sel.size} onClick={() => run("tag")}>Tag</button>
          <button className="wf-btn" disabled={!sel.size} onClick={() => run("untag", tag || null)}>Untag</button>
          {show === "archived"
            ? <button className="wf-btn" disabled={!sel.size} onClick={() => run("unarchive")}>Restore</button>
            : <button className="wf-btn" disabled={!sel.size} onClick={() => run("archive")}>Archive</button>}
          <button className="wf-btn danger" disabled={!sel.size} onClick={() => run("delete")}>Delete</button>
        </div>
        {error && <div className="cstate-error" style={{ margin: "0 26px 10px" }}>{error}</div>}
        <div className="membrowser-list">
          {rows.length === 0 && <p className="conversation-empty">No chats match.</p>}
          {rows.map((c) => (
            <div key={c.id} className={`membrowser-row chatmgr-item ${c.archived ? "is-off" : ""}`}>
              <input type="checkbox" className="membrowser-check" checked={sel.has(c.id)} aria-label={`Select ${c.title}`}
                onChange={(e) => setSel((s) => { const n = new Set(s); if (e.target.checked) n.add(c.id); else n.delete(c.id); return n; })} />
              <div className="membrowser-main">
                <button className="membrowser-text" onClick={() => onOpen(c.id)}>{c.pinned && "📌 "}{c.title || "Untitled"}</button>
                <div className="membrowser-meta">
                  <span>updated {when(c.updated_at)}</span>
                  {(c.tags || []).map((t) => <span key={t} className="mb-badge">#{t}</span>)}
                  {c.archived && <span className="mb-badge">archived</span>}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
