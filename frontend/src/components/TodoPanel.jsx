import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const COLUMNS = [
  { status: "todo", label: "To do" },
  { status: "in_progress", label: "In progress" },
  { status: "done", label: "Done" },
];

function BoardView({ todos, onMove, onRemove }) {
  const [dragId, setDragId] = useState(null);

  return (
    <div className="kanban-board">
      {COLUMNS.map((col) => (
        <div
          key={col.status}
          className="kanban-column"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (dragId) onMove(dragId, col.status);
            setDragId(null);
          }}
        >
          <div className="kanban-column-header">{col.label}</div>
          <div className="kanban-column-body">
            {todos
              .filter((t) => (t.status || (t.done ? "done" : "todo")) === col.status)
              .map((t) => (
                <div
                  key={t.id}
                  className="kanban-card"
                  draggable
                  onDragStart={() => setDragId(t.id)}
                >
                  <span>{t.text}</span>
                  <button className="icon-btn" onClick={() => onRemove(t.id)} title="Delete">
                    <Icon name="x" size={12} />
                  </button>
                </div>
              ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function TodoPanel({ onClose }) {
  const [todos, setTodos] = useState([]);
  const [draft, setDraft] = useState("");
  const [view, setView] = useState("list"); // "list" | "board"

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

  const moveTodo = async (id, status) => {
    setTodos((ts) => ts.map((t) => (t.id === id ? { ...t, status, done: status === "done" ? 1 : 0 } : t)));
    await api.updateTodo(id, { status });
  };

  const removeTodo = async (id) => {
    await api.deleteTodo(id);
    refresh();
  };

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div
        className="notes-modal"
        style={{ width: view === "board" ? "min(760px, calc(100vw - 3rem))" : "min(480px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="notes-header">
          <span>To-do</span>
          <div style={{ display: "flex", gap: "0.25rem", alignItems: "center" }}>
            <button
              className={`text-btn ${view === "list" ? "is-active" : ""}`}
              onClick={() => setView("list")}
            >
              List
            </button>
            <button
              className={`text-btn ${view === "board" ? "is-active" : ""}`}
              onClick={() => setView("board")}
            >
              Board
            </button>
            <button className="icon-btn" onClick={onClose} title="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
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
        {view === "board" ? (
          <BoardView todos={todos} onMove={moveTodo} onRemove={removeTodo} />
        ) : (
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
        )}
      </div>
    </div>
  );
}
