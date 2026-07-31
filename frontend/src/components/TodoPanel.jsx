import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

export default function TodoPanel({ onClose }) {
  const [todos, setTodos] = useState([]);
  const [draft, setDraft] = useState("");

  const refresh = () => api.listTodos().then(setTodos).catch(() => {});

  useEffect(() => {
    refresh();
  }, []);

  const addTodo = async () => {
    if (!draft.trim()) return;
    await api.createTodo(draft.trim());
    setDraft("");
    refresh();
  };

  const toggleDone = async (t) => {
    await api.updateTodo(t.id, { done: !t.done });
    refresh();
  };

  const removeTodo = async (id) => {
    await api.deleteTodo(id);
    refresh();
  };

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal" style={{ width: "min(480px, calc(100vw - 3rem))" }} onClick={(e) => e.stopPropagation()}>
        <div className="notes-header">
          <span>To-do</span>
          <button className="icon-btn" onClick={onClose} title="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div className="notes-add-row">
          <input
            className="settings-input"
            placeholder="Add a task…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addTodo()}
          />
          <button className="settings-btn-primary" onClick={addTodo}>
            Add
          </button>
        </div>
        <ul className="calendar-event-list">
          {todos.map((t) => (
            <li key={t.id} className="calendar-event-item">
              <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", flex: 1, cursor: "pointer" }}>
                <input type="checkbox" checked={!!t.done} onChange={() => toggleDone(t)} />
                <span style={{ textDecoration: t.done ? "line-through" : "none", opacity: t.done ? 0.5 : 1 }}>
                  {t.text}
                </span>
              </label>
              <button className="icon-btn" onClick={() => removeTodo(t.id)} title="Delete">
                <Icon name="x" size={13} />
              </button>
            </li>
          ))}
          {todos.length === 0 && <li className="conversation-empty">Nothing to do.</li>}
        </ul>
      </div>
    </div>
  );
}
