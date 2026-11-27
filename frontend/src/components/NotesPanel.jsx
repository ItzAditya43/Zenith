import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const COLORS = ["default", "yellow", "green", "blue", "pink"];

function NoteCard({ note, onUpdate, onDelete, onRestored }) {
  const [text, setText] = useState(note.content);
  const [history, setHistory] = useState(null);
  const dirty = text !== note.content;
  const showHistory = async () => setHistory(history ? null : await api.noteHistory(note.id).catch(() => []));
  const restore = async (v) => {
    await api.restoreNote(note.id, v.id);
    setHistory(null);
    onRestored();
  };

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
              aria-label={`Set color ${c}`}
            />
          ))}
        </div>
        <button
          className="icon-btn"
          onClick={() => onUpdate(note.id, { pinned: !note.pinned })}
          title={note.pinned ? "Unpin" : "Pin"}
          aria-label={note.pinned ? "Unpin" : "Pin"}
        >
          <Icon name="bolt" size={13} className={note.pinned ? "note-pin-active" : ""} />
        </button>
        <button className="icon-btn" onClick={showHistory} title="Earlier versions" aria-label="Earlier versions" aria-expanded={!!history}>
          <Icon name="clock" size={13} />
        </button>
        <button className="icon-btn" onClick={() => onDelete(note.id)} title="Delete" aria-label="Delete note">
          <Icon name="trash" size={13} />
        </button>
      </div>
      {history && (
        <ul className="note-history">
          {history.length === 0 && <li>No earlier versions.</li>}
          {history.map((v) => (
            <li key={v.id}>
              <span>{new Date(v.saved_at * 1000).toLocaleString()}</span>
              <p>{v.content.slice(0, 160)}{v.content.length > 160 ? "…" : ""}</p>
              <button className="text-btn" onClick={() => restore(v)}>Restore this</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Keep-style quick notes: a fast scratchpad for things that don't belong
 * buried in a chat thread. Pin + color is the whole organizing model —
 * deliberately no folders/tags. Search, Markdown export, and each note
 * keeps its last 20 versions.
 */
export default function NotesPanel({ onClose }) {
  const [notes, setNotes] = useState([]);
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");

  const refresh = () => api.listNotes(q).then(setNotes).catch(() => {});

  useEffect(() => {
    const t = setTimeout(refresh, 150);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

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
      <div className="notes-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="notes-panel-title">
        <div className="notes-header">
          <span id="notes-panel-title">Notes</span>
          <div style={{ display: "flex", gap: "0.25rem", alignItems: "center" }}>
            <a className="icon-btn" href={api.notesExportUrl()} download title="Export all notes as Markdown" aria-label="Export notes">
              <Icon name="download" size={14} />
            </a>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
        <div className="notes-add-row">
          <input className="settings-input" placeholder="Search notes…" aria-label="Search notes" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="notes-add-row">
          <textarea
            className="notes-add-input"
            placeholder="Take a note…"
            aria-label="Take a note"
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
            <NoteCard key={`${n.id}:${n.updated_at}`} note={n} onUpdate={updateNote} onDelete={deleteNote} onRestored={refresh} />
          ))}
          {notes.length === 0 && <p className="conversation-empty">{q ? "No notes match." : "No notes yet."}</p>}
        </div>
      </div>
    </div>
  );
}
