import { useState } from "react";
import ModelBadge from "./ModelBadge";
import MarkdownRenderer from "./MarkdownRenderer";
import { api } from "../lib/api";

const KIND_ICON = { image: "🖼", video: "🎬", document: "📄", audio: "🎙" };
const TOOL_ICON = { bash: "⌨", read_file: "📖", write_file: "📝", list_dir: "📁", web_search: "🔍", fetch_url: "🌐" };
const EDITABLE_DOC_EXTS = [".txt", ".md", ".csv", ".json"];

function DocumentChip({ attachment: a }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { filename, download_url } | { error }
  const editable = a.kind === "document" && EDITABLE_DOC_EXTS.some((ext) => a.name?.toLowerCase().endsWith(ext));

  const handleEdit = async () => {
    const instruction = window.prompt(`Edit "${a.name}" — describe the change:`);
    if (!instruction || !instruction.trim()) return;
    setBusy(true);
    setResult(null);
    try {
      const edited = await api.editDocument(a.id, instruction.trim());
      setResult({ filename: edited.filename, download_url: edited.download_url });
    } catch (err) {
      setResult({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="doc-chip-wrap">
      <span className="msg-attachment-chip">
        {KIND_ICON[a.kind] || "📎"} {a.name}
        {editable && (
          <button className="doc-chip-edit-btn" onClick={handleEdit} disabled={busy} title="Edit this document">
            {busy ? "…" : "✎"}
          </button>
        )}
      </span>
      {result?.download_url && (
        <a
          className="doc-chip-result"
          href={`${api.base}${result.download_url}`}
          target="_blank"
          rel="noopener noreferrer"
          download
        >
          ✓ {result.filename} — download
        </a>
      )}
      {result?.error && <span className="doc-chip-result doc-chip-error">⚠ {result.error}</span>}
    </div>
  );
}

function ToolCallCard({ call, onApprove, onDeny }) {
  const [expanded, setExpanded] = useState(false);
  const argsSummary =
    call.args?.command || call.args?.path || call.args?.query || call.args?.url || "";

  return (
    <div className={`tool-call-card tool-call-${call.status}`}>
      <button className="tool-call-header" onClick={() => setExpanded((v) => !v)}>
        <span className="tool-call-icon">{TOOL_ICON[call.tool] || "🔧"}</span>
        <span className="tool-call-name">{call.tool}</span>
        <span className="tool-call-summary">{argsSummary}</span>
        <span className={`tool-call-status-chip tool-call-status-${call.status}`}>
          {{
            running: "running…",
            pending: "needs approval",
            approving: "approving…",
            done: "done",
            denied: "denied",
          }[call.status] || call.status}
        </span>
      </button>

      {expanded && (
        <div className="tool-call-body">
          <pre className="tool-call-args">{JSON.stringify(call.args, null, 2)}</pre>
          {call.result != null && <pre className="tool-call-result">{call.result}</pre>}
        </div>
      )}

      {call.status === "pending" && (
        <div className="tool-call-actions">
          <button className="tool-call-approve-btn" onClick={() => onApprove?.(call.id)}>
            ✓ Approve
          </button>
          <button className="tool-call-deny-btn" onClick={() => onDeny?.(call.id)}>
            ✕ Deny
          </button>
        </div>
      )}
    </div>
  );
}

function BranchSwitcher({ siblings, activeId, onSwitch }) {
  if (!siblings || siblings.length < 2) return null;
  const idx = siblings.findIndex((s) => s.id === activeId);
  const pos = idx >= 0 ? idx : 0;
  const go = (delta) => {
    const next = siblings[(pos + delta + siblings.length) % siblings.length];
    onSwitch?.(next.id);
  };
  return (
    <div className="branch-switcher">
      <button onClick={() => go(-1)} title="Previous version">
        ‹
      </button>
      <span>
        {pos + 1}/{siblings.length}
      </span>
      <button onClick={() => go(1)} title="Next version">
        ›
      </button>
    </div>
  );
}

export default function MessageBubble({
  message,
  onRetry,
  onRegenerate,
  onEdit,
  onApproveTool,
  onDenyTool,
  siblings,
  onSwitchBranch,
}) {
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
      <div
        className={`msg-bubble ${isUser ? "msg-bubble-user" : "msg-bubble-assistant"}`}
        data-role={!isUser ? message.route_role : undefined}
      >
        {!isUser && message.model && (
          <ModelBadge model={message.model} role={message.route_role} reason={message.route_reason} />
        )}

        {message.attachments?.length > 0 && (
          <div className="msg-attachments">
            {message.attachments.map((a) => (
              <DocumentChip key={a.id} attachment={a} />
            ))}
          </div>
        )}

        {!isUser && message.toolCalls?.length > 0 && (
          <div className="tool-calls">
            {message.toolCalls.map((call) => (
              <ToolCallCard key={call.id} call={call} onApprove={onApproveTool} onDeny={onDenyTool} />
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
          <div className="msg-actions-row">
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
            <BranchSwitcher siblings={siblings} activeId={message.id} onSwitch={onSwitchBranch} />
          </div>
        )}
      </div>
    </div>
  );
}