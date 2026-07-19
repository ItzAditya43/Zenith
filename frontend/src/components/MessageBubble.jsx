import { useState } from "react";
import ModelBadge from "./ModelBadge";
import MarkdownRenderer from "./MarkdownRenderer";

const KIND_ICON = { image: "🖼", video: "🎬", document: "📄", audio: "🎙" };

export default function MessageBubble({ message, onRetry, onRegenerate, onEdit }) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(message.content || "");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard may be blocked */
    }
  };

  const saveEdit = () => {
    setEditing(false);
    if (editText.trim() && editText !== message.content) {
      onEdit?.(message, editText.trim());
    }
  };

  return (
    <div className={`msg-row ${isUser ? "msg-row-user" : "msg-row-assistant"}`}>
      <div className={`msg-bubble ${isUser ? "msg-bubble-user" : "msg-bubble-assistant"}`}>
        {!isUser && message.model && (
          <ModelBadge model={message.model} role={message.route_role} reason={message.route_reason} />
        )}

        {message.attachments?.length > 0 && (
          <div className="msg-attachments">
            {message.attachments.map((a) => (
              <span className="msg-attachment-chip" key={a.id}>
                {KIND_ICON[a.kind] || "📎"} {a.name}
              </span>
            ))}
          </div>
        )}

        {editing ? (
          <div className="msg-edit">
            <textarea
              className="msg-edit-input"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={4}
              autoFocus
            />
            <div className="msg-edit-actions">
              <button onClick={saveEdit}>Save</button>
              <button onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="msg-content">
            <MarkdownRenderer content={message.content} />
            {message.streaming && <span className="cursor-blink" data-role={message.route_role} />}
          </div>
        )}

        {!isUser && message.sources?.length > 0 && (
          <div className="msg-sources">
            {message.sources.map((s, i) => (
              <a
                key={s.url + i}
                className="msg-source-chip"
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                title={s.url}
              >
                🌐 {s.title || s.url}
              </a>
            ))}
          </div>
        )}

        {message.interrupted && (
          <div className="msg-interrupted">
            ⚠ {message.interrupted_reason || "Interrupted"}
            {onRetry && (
              <button className="msg-retry-btn" onClick={() => onRetry(message)}>
                Retry
              </button>
            )}
          </div>
        )}

        {!message.streaming && !editing && (
          <div className="msg-actions">
            <button onClick={copy} title="Copy">
              {copied ? "✓ Copied" : "⧉ Copy"}
            </button>
            {isUser && onEdit && (
              <button onClick={() => setEditing(true)} title="Edit & resend">
                ✎ Edit
              </button>
            )}
            {!isUser && onRegenerate && (
              <button onClick={() => onRegenerate(message)} title="Regenerate response">
                ↻ Regenerate
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}