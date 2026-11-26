import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import { useEscapeToClose } from "../hooks/useEscapeToClose";

export default function SnippetsPanel({ onClose, onInsert, onRunQuickAction }) {
  useEscapeToClose(onClose);
  const [tab, setTab] = useState("snippets"); // "snippets" | "actions"
  const [snippets, setSnippets] = useState([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const [actions, setActions] = useState([]);
  const [actionName, setActionName] = useState("");
  const [actionPrompt, setActionPrompt] = useState("");
  const [actionAutoSend, setActionAutoSend] = useState(false);
  const [actionError, setActionError] = useState("");
  const [packPreview, setPackPreview] = useState(null); // { pack, preview, include:Set }
  const [packMsg, setPackMsg] = useState("");

  const openPackFile = async (file) => {
    setPackMsg("");
    try {
      const pack = JSON.parse(await file.text());
      const preview = await api.previewPack(pack);
      setPackPreview({ pack, preview, include: new Set(preview.items.filter((i) => !i.problem && !i.duplicate).map((i) => `${i.kind}:${i.index}`)) });
    } catch (e) { setPackMsg(e.message || "That file couldn't be read."); }
  };
  const doImport = async () => {
    const r = await api.importPack(packPreview.pack, [...packPreview.include]);
    const a = r.added;
    setPackMsg(`Added ${a.quick_actions} quick action${a.quick_actions === 1 ? "" : "s"}, ${a.personas} persona${a.personas === 1 ? "" : "s"} and ${a.automation_rules} automation rule${a.automation_rules === 1 ? "" : "s"}${a.automation_rules ? " (switched off — turn them on in Settings → Automation)" : ""}.`);
    setPackPreview(null);
    refreshActions();
  };

  const refresh = () => api.listSnippets().then(setSnippets).catch(() => {});
  const refreshActions = () => api.listQuickActions().then(setActions).catch(() => {});

  useEffect(() => {
    refresh();
    refreshActions();
  }, []);

  const add = async () => {
    if (!title.trim() || !content.trim()) return;
    await api.createSnippet(title.trim(), content.trim());
    setTitle("");
    setContent("");
    refresh();
  };

  const remove = async (id) => {
    await api.deleteSnippet(id);
    refresh();
  };

  const addAction = async () => {
    if (!actionName.trim() || !actionPrompt.trim()) return;
    setActionError("");
    try {
      await api.createQuickAction(actionName.trim(), actionPrompt.trim(), actionAutoSend);
    } catch (e) {
      setActionError(e.message);
      return;
    }
    setActionName("");
    setActionPrompt("");
    setActionAutoSend(false);
    refreshActions();
  };;

  const removeAction = async (id) => {
    await api.deleteQuickAction(id);
    refreshActions();
  };

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div
        className="notes-modal"
        style={{ width: "min(560px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Snippets and quick actions"
      >
        <div className="notes-header">
          <div style={{ display: "flex", gap: "0.25rem" }}>
            <button className={`text-btn ${tab === "snippets" ? "is-active" : ""}`} onClick={() => setTab("snippets")}>
              Snippets
            </button>
            <button className={`text-btn ${tab === "actions" ? "is-active" : ""}`} onClick={() => setTab("actions")}>
              Quick actions
            </button>
          </div>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        {tab === "snippets" ? (
          <>
            <div className="notes-add-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
              <input
                className="settings-input"
                placeholder='Title (e.g. "Bug report template")'
                aria-label="Snippet title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
              <textarea
                className="settings-input notes-add-input"
                placeholder="Snippet content…"
                aria-label="Snippet content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={3}
              />
              <button className="settings-btn-primary" onClick={add} style={{ alignSelf: "flex-end" }}>
                Save snippet
              </button>
            </div>
            <ul className="calendar-event-list">
              {snippets.map((s) => (
                <li key={s.id} className="calendar-event-item">
                  <button
                    style={{ flex: 1, textAlign: "left", cursor: onInsert ? "pointer" : "default" }}
                    onClick={() => onInsert && onInsert(s.content)}
                    title={onInsert ? "Insert into composer" : undefined}
                  >
                    <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>{s.title}</div>
                    <div style={{ fontSize: "var(--text-xs)", color: "var(--text-tertiary)", whiteSpace: "pre-wrap" }}>
                      {s.content.length > 140 ? s.content.slice(0, 140) + "…" : s.content}
                    </div>
                  </button>
                  <button className="conversation-delete" style={{ opacity: 1 }} onClick={() => remove(s.id)} title="Delete" aria-label={`Delete snippet "${s.title}"`}>
                    <Icon name="x" size={13} />
                  </button>
                </li>
              ))}
              {snippets.length === 0 && <p className="conversation-empty">No snippets yet.</p>}
            </ul>
          </>
        ) : (
          <>
            <p className="settings-section-desc" style={{ padding: "0 1rem" }}>
              Reusable commands, one keystroke away from the command palette (⌘K). Add fields like{" "}
              <code>{"{{file}}"}</code> or <code>{"{{tone|friendly}}"}</code> and Zenith asks for them each time;{" "}
              <code>{"{{date}}"}</code> and <code>{"{{time}}"}</code> fill themselves.
            </p>
            <div className="pack-bar">
              <a className="wf-btn" href={api.packExportUrl()} download><Icon name="download" size={13} /> Export pack</a>
              <label className="wf-btn">
                <Icon name="plus" size={13} /> Import pack
                <input type="file" accept=".json,application/json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) openPackFile(f); e.target.value = ""; }} />
              </label>
              <span className="wf-muted" style={{ margin: 0 }}>Packs bundle quick actions, personas and automation rules.</span>
            </div>
            {packMsg && <div className="cstate-error" style={{ margin: "0 1rem 0.5rem" }}>{packMsg}</div>}
            {packPreview && (
              <div className="pack-preview">
                <strong>{packPreview.preview.name}</strong>
                {packPreview.preview.description && <p>{packPreview.preview.description}</p>}
                <ul>
                  {packPreview.preview.items.map((it) => {
                    const key = `${it.kind}:${it.index}`;
                    const blocked = !!it.problem || it.duplicate;
                    return (
                      <li key={key} className={blocked ? "is-blocked" : ""}>
                        <input type="checkbox" disabled={blocked} checked={packPreview.include.has(key)}
                          onChange={(e) => setPackPreview((p) => { const n = new Set(p.include); if (e.target.checked) n.add(key); else n.delete(key); return { ...p, include: n }; })} />
                        <div>
                          <span className="mb-badge">{it.kind.replace("_", " ")}</span> <b>{it.name || "(no name)"}</b>
                          {it.duplicate && <em> — already have it</em>}
                          {it.problem && <em className="warn"> — {it.problem}</em>}
                          {it.permissions.length > 0 && <small>{it.permissions.join(" · ")}</small>}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <div className="pack-actions">
                  <button className="wf-btn" onClick={() => setPackPreview(null)}>Cancel</button>
                  <button className="wf-btn primary" onClick={doImport} disabled={!packPreview.include.size}>Import {packPreview.include.size}</button>
                </div>
              </div>
            )}
            <div className="notes-add-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
              <input
                className="settings-input"
                placeholder='Name (e.g. "Explain this error")'
                aria-label="Quick action name"
                value={actionName}
                onChange={(e) => setActionName(e.target.value)}
              />
              <textarea
                className="settings-input notes-add-input"
                placeholder="Prompt template…"
                aria-label="Prompt template"
                value={actionPrompt}
                onChange={(e) => setActionPrompt(e.target.value)}
                rows={3}
              />
              <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "var(--text-xs)" }}>
                <input type="checkbox" checked={actionAutoSend} onChange={(e) => setActionAutoSend(e.target.checked)} />
                Send immediately (skip review)
              </label>
              {actionError && <div className="cstate-error">{actionError}</div>}
              <button className="settings-btn-primary" onClick={addAction} style={{ alignSelf: "flex-end" }}>
                Save quick action
              </button>
            </div>
            <ul className="calendar-event-list">
              {actions.map((a) => (
                <li key={a.id} className="calendar-event-item">
                  <button
                    style={{ flex: 1, textAlign: "left", cursor: "pointer" }}
                    onClick={() => onRunQuickAction && onRunQuickAction(a)}
                    title={a.auto_send ? "Run now" : "Insert into composer"}
                  >
                    <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                      {a.name} {a.auto_send && <Icon name="bolt" size={11} />}
                      {a.fields?.length > 0 && <span className="mb-badge" style={{ marginLeft: 6 }}>asks for {a.fields.map((f) => f.name).join(", ")}</span>}
                    </div>
                    <div style={{ fontSize: "var(--text-xs)", color: "var(--text-tertiary)", whiteSpace: "pre-wrap" }}>
                      {a.prompt_template.length > 140 ? a.prompt_template.slice(0, 140) + "…" : a.prompt_template}
                    </div>
                  </button>
                  <button className="conversation-delete" style={{ opacity: 1 }} onClick={() => removeAction(a.id)} title="Delete" aria-label={`Delete quick action "${a.name}"`}>
                    <Icon name="x" size={13} />
                  </button>
                </li>
              ))}
              {actions.length === 0 && <p className="conversation-empty">No quick actions yet.</p>}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
