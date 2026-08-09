import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

export default function SnippetsPanel({ onClose, onInsert, onRunQuickAction }) {
  const [tab, setTab] = useState("snippets"); // "snippets" | "actions"
  const [snippets, setSnippets] = useState([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const [actions, setActions] = useState([]);
  const [actionName, setActionName] = useState("");
  const [actionPrompt, setActionPrompt] = useState("");
  const [actionAutoSend, setActionAutoSend] = useState(false);

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
    await api.createQuickAction(actionName.trim(), actionPrompt.trim(), actionAutoSend);
    setActionName("");
    setActionPrompt("");
    setActionAutoSend(false);
    refreshActions();
  };

  const removeAction = async (id) => {
    await api.deleteQuickAction(id);
    refreshActions();
  };

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal" style={{ width: "min(560px, calc(100vw - 3rem))" }} onClick={(e) => e.stopPropagation()}>
        <div className="notes-header">
          <div style={{ display: "flex", gap: "0.25rem" }}>
            <button className={`text-btn ${tab === "snippets" ? "is-active" : ""}`} onClick={() => setTab("snippets")}>
              Snippets
            </button>
            <button className={`text-btn ${tab === "actions" ? "is-active" : ""}`} onClick={() => setTab("actions")}>
              Quick actions
            </button>
          </div>
          <button className="icon-btn" onClick={onClose} title="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        {tab === "snippets" ? (
          <>
            <div className="notes-add-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
              <input
                className="settings-input"
                placeholder='Title (e.g. "Bug report template")'
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
              <textarea
                className="settings-input notes-add-input"
                placeholder="Snippet content…"
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
                  <button className="conversation-delete" style={{ opacity: 1 }} onClick={() => remove(s.id)} title="Delete">
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
              Reusable commands, one keystroke away from the command palette (⌘K). "Auto-send"
              sends immediately instead of just filling the composer for you to review first.
            </p>
            <div className="notes-add-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
              <input
                className="settings-input"
                placeholder='Name (e.g. "Explain this error")'
                value={actionName}
                onChange={(e) => setActionName(e.target.value)}
              />
              <textarea
                className="settings-input notes-add-input"
                placeholder="Prompt template…"
                value={actionPrompt}
                onChange={(e) => setActionPrompt(e.target.value)}
                rows={3}
              />
              <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "var(--text-xs)" }}>
                <input type="checkbox" checked={actionAutoSend} onChange={(e) => setActionAutoSend(e.target.checked)} />
                Send immediately (skip review)
              </label>
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
                    </div>
                    <div style={{ fontSize: "var(--text-xs)", color: "var(--text-tertiary)", whiteSpace: "pre-wrap" }}>
                      {a.prompt_template.length > 140 ? a.prompt_template.slice(0, 140) + "…" : a.prompt_template}
                    </div>
                  </button>
                  <button className="conversation-delete" style={{ opacity: 1 }} onClick={() => removeAction(a.id)} title="Delete">
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
