import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const KIND_LABELS = {
  document: "Document",
  folder: "Watched folder file",
  message: "Conversation history",
  memory: "Memory",
};

function formatTimestamp(seconds) {
  if (!seconds) return "unknown";
  try {
    return new Date(seconds * 1000).toLocaleString();
  } catch (_) {
    return "unknown";
  }
}

function SourceRow({ source, onDelete, deleting }) {
  const kindLabel = KIND_LABELS[source.source_kind] || source.source_kind;
  return (
    <div className="health-row">
      <div className="health-row-main">
        <span className="health-row-label">{source.label}</span>
      </div>
      <div className="health-row-detail">
        <span className="health-row-field">{kindLabel}</span>
        <span className="health-row-field">{source.chunk_count} chunk{source.chunk_count === 1 ? "" : "s"}</span>
        <span className="health-row-field">last indexed: {formatTimestamp(source.last_indexed)}</span>
        {source.detail && <span className="health-row-field">{source.detail}</span>}
      </div>
      <div style={{ marginTop: "var(--space-1)" }}>
        <button
          className="icon-btn"
          onClick={() => onDelete(source)}
          disabled={deleting}
          title="Remove from RAG index"
          aria-label={`Remove ${source.label} from RAG index`}
        >
          <Icon name="trash" size={14} />
        </button>
      </div>
    </div>
  );
}

/** Lists every source currently indexed for retrieval-augmented context —
 * uploaded documents, watched-folder files, cross-conversation message
 * history, and stored memories — with chunk counts and a delete action.
 * Standalone overlay; mount with { onClose }. Mirrors HealthPanel's
 * overlay/dialog structure and CSS classes. */
export default function RagSourcesPanel({ onClose }) {
  const [sources, setSources] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .listRagSources()
      .then((res) => setSources(res.sources || []))
      .catch((err) => setError(err.message || "Failed to load RAG sources."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const handleDelete = async (source) => {
    if (
      !window.confirm(
        `Remove "${source.label}" (${source.chunk_count} chunk${source.chunk_count === 1 ? "" : "s"}) from the RAG index? This can't be undone.`
      )
    ) {
      return;
    }
    const key = `${source.source_kind}:${source.source_id}`;
    setDeletingId(key);
    try {
      await api.deleteRagSource(source.source_id, source.source_kind);
      setSources((prev) =>
        (prev || []).filter(
          (s) => !(s.source_id === source.source_id && s.source_kind === source.source_kind)
        )
      );
    } catch (err) {
      setError(err.message || "Failed to delete source.");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div
        className="calendar-modal"
        style={{ width: "min(560px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="rag-sources-panel-title"
      >
        <div className="calendar-header">
          <span id="rag-sources-panel-title">RAG sources</span>
          <div style={{ display: "flex", gap: "var(--space-1)" }}>
            <button className="icon-btn" onClick={load} title="Refresh" aria-label="Refresh">
              <Icon name="rotate-ccw" size={14} />
            </button>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
        <div style={{ padding: "var(--space-3) var(--space-4)", maxHeight: "75vh", overflowY: "auto" }}>
          {loading && !sources && <p className="conversation-empty">Loading…</p>}
          {error && <p className="conversation-empty">{error}</p>}
          {sources && sources.length === 0 && !loading && (
            <p className="conversation-empty">Nothing indexed yet.</p>
          )}
          {sources && sources.length > 0 && (
            <div className="health-list">
              {sources.map((source) => (
                <SourceRow
                  key={`${source.source_kind}:${source.source_id}`}
                  source={source}
                  onDelete={handleDelete}
                  deleting={deletingId === `${source.source_kind}:${source.source_id}`}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
