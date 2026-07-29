import { useState } from "react";
import ModelBadge from "./ModelBadge";
import MarkdownRenderer from "./MarkdownRenderer";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const KIND_ICON = { image: "image", video: "video", document: "file-text", audio: "headphones" };
const TOOL_ICON = {
  bash: "terminal", read_file: "book-open", write_file: "file-pen", list_dir: "folder-open",
  web_search: "search", fetch_url: "link",
  shell_start: "terminal", shell_output: "terminal", shell_write_stdin: "terminal",
  shell_kill: "square", shell_list: "layers",
};
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
        <Icon name={KIND_ICON[a.kind] || "paperclip"} size={14} /> {a.name}
        {editable && (
          <button className="doc-chip-edit-btn" onClick={handleEdit} disabled={busy} title="Edit this document">
            {busy ? "…" : <Icon name="pencil" size={13} />}
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
          <Icon name="check" size={13} /> {result.filename} — download
        </a>
      )}
      {result?.error && (
        <span className="doc-chip-result doc-chip-error">
          <Icon name="alert-triangle" size={13} /> {result.error}
        </span>
      )}
    </div>
  );
}

function DiffView({ diff }) {
  const lines = diff.split("\n");
  return (
    <pre className="tool-call-diff">
      {lines.map((line, i) => {
        const kind = line.startsWith("+") && !line.startsWith("+++")
          ? "add"
          : line.startsWith("-") && !line.startsWith("---")
          ? "del"
          : line.startsWith("@@")
          ? "hunk"
          : "ctx";
        return (
          <div key={i} className={`diff-line diff-line-${kind}`}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

const REVERTABLE_TOOLS = new Set(["edit_file", "write_file"]);

function ToolCallCard({ call, onApprove, onDeny, onRevert }) {
  const [expanded, setExpanded] = useState(() => Boolean(call.diff));
  const [reverting, setReverting] = useState(false);
  const argsSummary =
    call.args?.command || call.args?.path || call.args?.query || call.args?.url ||
    (call.args?.session_id ? `session ${call.args.session_id.slice(0, 8)}` : "");

  const canRevert =
    call.status === "done" && REVERTABLE_TOOLS.has(call.tool) && call.diff && onRevert;

  const handleRevert = async () => {
    setReverting(true);
    try {
      await onRevert?.(call.id);
    } finally {
      setReverting(false);
    }
  };

  return (
    <div className={`tool-call-card tool-call-${call.status}`}>
      <button className="tool-call-header" onClick={() => setExpanded((v) => !v)}>
        <span className="tool-call-icon"><Icon name={TOOL_ICON[call.tool] || "wrench"} size={14} /></span>
        <span className="tool-call-name">{call.tool}</span>
        <span className="tool-call-summary">{argsSummary}</span>
        <span className={`tool-call-status-chip tool-call-status-${call.status}`}>
          {{
            running: "running…",
            pending: "needs approval",
            approving: "approving…",
            done: "done",
            denied: "denied",
            reverted: "reverted",
          }[call.status] || call.status}
        </span>
      </button>

      {expanded && (
        <div className="tool-call-body">
          {call.diff ? <DiffView diff={call.diff} /> : <pre className="tool-call-args">{JSON.stringify(call.args, null, 2)}</pre>}
          {call.result != null && <pre className="tool-call-result">{call.result}</pre>}
        </div>
      )}

      {call.status === "pending" && (
        <div className="tool-call-actions">
          <button className="tool-call-approve-btn" onClick={() => onApprove?.(call.id)}>
            <Icon name="check" size={13} /> Approve
          </button>
          <button className="tool-call-deny-btn" onClick={() => onDeny?.(call.id)}>
            <Icon name="x" size={13} /> Deny
          </button>
        </div>
      )}

      {canRevert && (
        <div className="tool-call-actions">
          <button className="tool-call-revert-btn" onClick={handleRevert} disabled={reverting}>
            <Icon name="rotate-ccw" size={13} /> {reverting ? "Reverting…" : "Revert this edit"}
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
        <Icon name="chevron-left" size={13} />
      </button>
      <span>
        {pos + 1}/{siblings.length}
      </span>
      <button onClick={() => go(1)} title="Next version">
        <Icon name="chevron-right" size={13} />
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
  onRevertTool,
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
              <ToolCallCard key={call.id} call={call} onApprove={onApproveTool} onDeny={onDenyTool} onRevert={onRevertTool} />
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
            {message.streaming && !message.content ? (
              <span className="thinking-dots" data-role={message.route_role} aria-label="Thinking">
                <span />
                <span />
                <span />
              </span>
            ) : (
              <>
                <MarkdownRenderer content={message.content} />
                {message.streaming && <span className="cursor-blink" data-role={message.route_role} />}
              </>
            )}
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
                <Icon name="link" size={12} /> {s.title || s.url}
              </a>
            ))}
          </div>
        )}

        {message.interrupted && (
          <div className="msg-interrupted">
            <Icon name="alert-triangle" size={13} /> {message.interrupted_reason || "Interrupted"}
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
                {copied ? <><Icon name="check" size={13} /> Copied</> : <><Icon name="copy" size={13} /> Copy</>}
              </button>
              {isUser && onEdit && (
                <button onClick={() => setEditing(true)} title="Edit & resend">
                  <Icon name="pencil" size={13} /> Edit
                </button>
              )}
              {!isUser && onRegenerate && (
                <button onClick={() => onRegenerate(message)} title="Regenerate response">
                  <Icon name="rotate-ccw" size={13} /> Regenerate
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