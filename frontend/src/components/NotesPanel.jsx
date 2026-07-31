import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const COLORS = ["default", "yellow", "green", "blue", "pink"];

function NoteCard({ note, onUpdate, onDelete }) {
  const [text, setText] = useState(note.content);
  const dirty = text !== note.content;

  return (
    <div className={`note-card note-card-${note.color}`}>
      <textarea
        className="note-card-textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => dirty && onUpdate(note.id, { content: text })}
      />
      <div className="note-card-footer">
        <div className="note-card-colors">
          {COLORS.map((c) => (
            <button
              key={c}
              className={`note-color-dot note-color-${c} ${note.color === c ? "is-active" : ""}`}
              onClick={() => onUpdate(note.id, { color: c })}
              title={c}
            />
          ))}
        </div>
        <button
          className="icon-btn"
          onClick={() => onUpdate(note.id, { pinned: !note.pinned })}
          title={note.pinned ? "Unpin" : "Pin"}
        >
          <Icon name="bolt" size={13} className={note.pinned ? "note-pin-active" : ""} />
        </button>
        <button className="icon-btn" onClick={() => onDelete(note.id)} title="Delete">
          <Icon name="trash" size={13} />
        </button>
      </div>
    </div>
  );
}

/**
 * Keep-style quick notes: a fast scratchpad for things that don't belong
 * buried in a chat thread. Pin + color is the whole organizing model —
 * deliberately no folders/tags.
 */
export default function NotesPanel({ onClose }) {
  const [notes, setNotes] = useState([]);
  const [draft, setDraft] = useState("");

  const refresh = () => api.listNotes().then(setNotes).catch(() => {});

  useEffect(() => {
    refresh();
  }, []);

  const addNote = async () => {
    if (!draft.trim()) return;
    await api.createNote(draft.trim());
    setDraft("");
    refresh();
  };

  const updateNote = async (id, patch) => {
    setNotes((ns) => ns.map((n) => (n.id === id ? { ...n, ...patch } : n)));
    await api.updateNote(id, patch);
    refresh();
  };

  const deleteNote = async (id) => {
    await api.deleteNote(id);
    refresh();
  };

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal" onClick={(e) => e.stopPropagation()}>
        <div className="notes-header">
          <span>Notes</span>
          <button className="icon-btn" onClick={onClose} title="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div className="notes-add-row">
          <textarea
            className="notes-add-input"
            placeholder="Take a note…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) addNote();
            }}
          />
          <button className="settings-btn-primary" onClick={addNote}>
            Add
          </button>
        </div>
        <div className="notes-grid">
          {notes.map((n) => (
            <NoteCard key={n.id} note={n} onUpdate={updateNote} onDelete={deleteNote} />
          ))}
          {notes.length === 0 && <p className="conversation-empty">No notes yet.</p>}
        </div>
      </div>
    </div>
  );
}
