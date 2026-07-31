import { useState } from "react";
import Icon from "./Icon.jsx";

/**
 * Bind a conversation to 2+ personas instead of one — each configured
 * persona replies in turn, reacting to what the others already said,
 * simulating a multi-bot group chat.
 */
export default function GroupChatPicker({ personas, selectedIds, onChange, onClose }) {
  const [local, setLocal] = useState(selectedIds);

  const toggle = (id) => {
    setLocal((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  };

  return (
    <div className="branch-tree-panel" style={{ width: "min(320px, calc(100vw - 2rem))" }}>
      <div className="branch-tree-header">
        <span>Group chat</span>
        <button className="icon-btn" onClick={onClose} title="Close">
          <Icon name="x" size={14} />
        </button>
      </div>
      <div style={{ padding: "0.5rem 0.75rem" }}>
        <p className="settings-section-desc" style={{ marginTop: 0 }}>
          Pick 2+ personas — each replies in turn per message, reacting to the others.
        </p>
        {personas.map((p) => (
          <label key={p.id} className="settings-row" style={{ gap: "0.5rem", padding: "0.25rem 0", cursor: "pointer" }}>
            <input type="checkbox" checked={local.includes(p.id)} onChange={() => toggle(p.id)} />
            <span>
              {p.icon ? `${p.icon} ` : ""}
              {p.name}
            </span>
          </label>
        ))}
        {personas.length === 0 && <p className="conversation-empty">No personas yet — create some in Settings.</p>}
        <button
          className="settings-btn-primary"
          style={{ marginTop: "0.5rem" }}
          onClick={() => {
            onChange(local.length >= 2 ? local : []);
            onClose();
          }}
        >
          {local.length >= 2 ? `Start group chat (${local.length})` : "Need at least 2 — or clear to disable"}
        </button>
      </div>
    </div>
  );
}
