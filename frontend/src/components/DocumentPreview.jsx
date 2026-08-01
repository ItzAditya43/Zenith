import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const TEXT_EXTS = [".txt", ".md", ".csv", ".json", ".log"];

/** Inline preview for a document attachment or citation — PDFs render via
 * the browser's native viewer, plain-text formats are fetched and shown
 * directly, everything else falls back to "no inline preview, download."
 * Optionally jumps to/highlights a specific chunk when opened from a
 * citation (`highlightText`). */
export default function DocumentPreview({ attachmentId, filename, highlightText, onClose }) {
  const [text, setText] = useState(null);
  const [error, setError] = useState(null);
  const url = `${api.base}/api/attachments/${attachmentId}/download`;
  const lower = (filename || "").toLowerCase();
  const isPdf = lower.endsWith(".pdf");
  const isText = TEXT_EXTS.some((ext) => lower.endsWith(ext));

  useEffect(() => {
    if (!isText) return;
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error("Couldn't load file.");
        return r.text();
      })
      .then(setText)
      .catch((err) => setError(err.message));
  }, [url, isText]);

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div className="calendar-modal" style={{ width: "min(760px, calc(100vw - 3rem))" }} onClick={(e) => e.stopPropagation()}>
        <div className="calendar-header">
          <span>
            <Icon name="file-text" size={14} /> {filename}
          </span>
          <div style={{ display: "flex", gap: "8px" }}>
            <a className="icon-btn" href={url} target="_blank" rel="noopener noreferrer" download title="Download">
              <Icon name="download" size={14} />
            </a>
            <button className="icon-btn" onClick={onClose} title="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
        <div style={{ height: "70vh", overflow: "auto" }}>
          {isPdf && <embed src={url} type="application/pdf" width="100%" height="100%" />}
          {isText && !error && (
            <pre className="doc-preview-text">
              {highlightText && text?.includes(highlightText)
                ? text.split(highlightText).reduce((acc, part, i, arr) => {
                    acc.push(part);
                    if (i < arr.length - 1) acc.push(<mark key={i}>{highlightText}</mark>);
                    return acc;
                  }, [])
                : text ?? "Loading…"}
            </pre>
          )}
          {!isPdf && !isText && (
            <p className="conversation-empty" style={{ padding: "var(--space-4)" }}>
              No inline preview for this file type — use download instead.
            </p>
          )}
          {error && <p className="settings-error" style={{ padding: "var(--space-4)" }}>{error}</p>}
        </div>
      </div>
    </div>
  );
}
