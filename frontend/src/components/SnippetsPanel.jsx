import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

export default function SnippetsPanel({ onClose, onInsert }) {
  const [snippets, setSnippets] = useState([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const refresh = () => api.listSnippets().then(setSnippets).catch(() => {});

  useEffect(() => {
    refresh();
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

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal" style={{ width: "min(560px, calc(100vw - 3rem))" }} onClick={(e) => e.stopPropagation()}>
        <div className="notes-header">
          <span>Prompt snippets</span>
          <button className="icon-btn" onClick={onClose} title="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
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
      </div>
    </div>
  );
}
