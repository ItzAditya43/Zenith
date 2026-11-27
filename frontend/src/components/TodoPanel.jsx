import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import { useEscapeToClose } from "../hooks/useEscapeToClose";
import Select from "./Select.jsx";

const PRIORITY = ["", "Low", "Medium", "High"];
const dueLabel = (ts) => {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const days = Math.floor((d.setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86400000);
  return days < 0 ? `overdue ${-days}d` : days === 0 ? "today" : days === 1 ? "tomorrow" : new Date(ts * 1000).toLocaleDateString();
};
const toDateInput = (ts) => (ts ? new Date(ts * 1000).toISOString().slice(0, 10) : "");
const fromDateInput = (v) => (v ? new Date(`${v}T09:00:00`).getTime() / 1000 : null);

function Meta({ t }) {
  return (
    <span className="todo-meta">
      {t.priority > 0 && <span className={`todo-pri p${t.priority}`}>{PRIORITY[t.priority]}</span>}
      {t.due_ts && <span className={`todo-due ${!t.done && dueLabel(t.due_ts).startsWith("overdue") ? "is-overdue" : ""}`}>{dueLabel(t.due_ts)}</span>}
      {t.project && <span className="todo-proj">{t.project}</span>}
    </span>
  );
}

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
                  <span>{t.text}<Meta t={t} /></span>
                  <Select
                    className="kanban-card-move"
                    value={col.status}
                    aria-label={`Move "${t.text}" to a different column`}
                    title="Move to…"
                    onChange={(e) => onMove(t.id, e.target.value)}
                  >
                    {COLUMNS.map((c) => (
                      <option key={c.status} value={c.status}>{c.label}</option>
                    ))}
                  </Select>
                  <button className="icon-btn" onClick={() => onRemove(t.id)} title="Delete" aria-label={`Delete "${t.text}"`}>
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
  const [q, setQ] = useState("");
  const [project, setProject] = useState("");
  const [projects, setProjects] = useState([]);
  const [editing, setEditing] = useState(null);
  useEscapeToClose(onClose);

  const refresh = () => {
    api.listTodos(q, project).then(setTodos).catch(() => {});
    api.todoProjects().then(setProjects).catch(() => {});
  };

  useEffect(() => {
    const t = setTimeout(refresh, 150);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, project]);

  const addTodo = async () => {
    if (!draft.trim()) return;
    await api.createTodo(draft.trim(), null, project ? { project } : {});
    setDraft("");
    refresh();
  };

  const patch = async (id, p) => {
    setTodos((ts) => ts.map((t) => (t.id === id ? { ...t, ...p } : t)));
    await api.updateTodo(id, p);
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
        role="dialog"
        aria-modal="true"
        aria-label="To-do"
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
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
        <div className="notes-add-row">
          <input className="settings-input" placeholder="Search tasks…" aria-label="Search tasks" value={q} onChange={(e) => setQ(e.target.value)} />
          {projects.length > 0 && (
            <Select className="settings-select" style={{ flex: "0 0 140px" }} value={project} onChange={(e) => setProject(e.target.value)} aria-label="Filter by project">
              <option value="">All projects</option>
              {projects.map((p) => <option key={p} value={p}>{p}</option>)}
            </Select>
          )}
        </div>
        <div className="notes-add-row">
          <input
            className="settings-input"
            placeholder="Add a task…"
            aria-label="Add a task"
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
                    <Meta t={t} />
                  </span>
                </label>
                <button className="icon-btn" onClick={() => setEditing(editing === t.id ? null : t.id)} title="Details" aria-label={`Edit details of "${t.text}"`} aria-expanded={editing === t.id}>
                  <Icon name="pencil" size={13} />
                </button>
                <button className="icon-btn" onClick={() => removeTodo(t.id)} title="Delete" aria-label={`Delete "${t.text}"`}>
                  <Icon name="x" size={13} />
                </button>
                {editing === t.id && (
                  <div className="todo-edit">
                    <Select className="settings-select" value={t.priority || 0} aria-label="Priority" onChange={(e) => patch(t.id, { priority: Number(e.target.value) })}>
                      <option value={0}>No priority</option>
                      <option value={1}>Low</option>
                      <option value={2}>Medium</option>
                      <option value={3}>High</option>
                    </Select>
                    <input type="date" className="settings-input" aria-label="Due date" value={toDateInput(t.due_ts)} onChange={(e) => patch(t.id, { due_ts: fromDateInput(e.target.value) })} />
                    <input className="settings-input" aria-label="Project" placeholder="Project" list="todo-projects" defaultValue={t.project || ""}
                      onBlur={(e) => e.target.value !== (t.project || "") && patch(t.id, { project: e.target.value })} />
                    <datalist id="todo-projects">{projects.map((p) => <option key={p} value={p} />)}</datalist>
                  </div>
                )}
              </li>
            ))}
            {todos.length === 0 && <li className="conversation-empty">{q || project ? "No tasks match." : "Nothing to do."}</li>}
          </ul>
        )}
      </div>
    </div>
  );
}
