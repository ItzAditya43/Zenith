import { useEffect, useState } from "react";
import ModelBadge from "./ModelBadge";
import MarkdownRenderer from "./MarkdownRenderer";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import RegenerationDiff from "./RegenerationDiff.jsx";
import DocumentPreview from "./DocumentPreview.jsx";

const KIND_ICON = { image: "image", video: "video", document: "file-text", audio: "headphones" };
const TOOL_ICON = {
  bash: "terminal", read_file: "book-open", write_file: "file-pen", list_dir: "folder-open",
  web_search: "search", fetch_url: "link",
  shell_start: "terminal", shell_output: "terminal", shell_write_stdin: "terminal",
  shell_kill: "square", shell_list: "layers", spawn_subagent: "bot",
  browser_navigate: "globe", browser_click: "globe", browser_type: "globe",
  browser_get_text: "globe", browser_close: "globe", git: "git-branch",
  run_checks: "check-circle",
};
const EDITABLE_DOC_EXTS = [".txt", ".md", ".csv", ".json"];

// Reasoning models (deepseek-r1, qwq, …) emit their scratch-work wrapped in
// <think>...</think> before the real answer. Split it out so it renders as
// a collapsible trace instead of dumping raw reasoning into the reply —
// handles an unterminated tag too (still streaming mid-thought).
function splitThinking(content) {
  if (!content || !content.includes("<think>")) return { trace: null, rest: content };
  const start = content.indexOf("<think>") + "<think>".length;
  const endIdx = content.indexOf("</think>");
  if (endIdx === -1) {
    return { trace: content.slice(start), rest: "", thinking: true };
  }
  const trace = content.slice(start, endIdx);
  const rest = content.slice(0, content.indexOf("<think>")) + content.slice(endIdx + "</think>".length);
  return { trace, rest };
}

// The backend gives up on a truly stuck model after stream_idle_timeout_
// seconds (120s default) and reports a clear error — but 2 minutes of
// silence with zero feedback is a long time to just stare at three dots.
// This is a much earlier, purely informational heads-up; it never
// cancels anything itself (Composer's Stop button already does that).
function SlowReplyHint() {
  const [elapsedMs, setElapsedMs] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsedMs(Date.now() - start), 1000);
    return () => clearInterval(id);
  }, []);
  if (elapsedMs < 15000) return null;
  return (
    <div className="slow-reply-hint">
      Taking longer than usual ({Math.round(elapsedMs / 1000)}s) — possibly a model too large
      for your GPU/RAM. You can stop and try a smaller one in Settings → Model routing.
    </div>
  );
}

function ThinkingTrace({ trace, thinking }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="thinking-trace">
      <button className="thinking-trace-toggle" onClick={() => setOpen((v) => !v)}>
        <Icon name={open ? "chevron-down" : "chevron-right"} size={12} />
        {thinking ? "Thinking…" : "Reasoning"}
      </button>
      {open && <pre className="thinking-trace-body">{trace}</pre>}
    </div>
  );
}

function DocumentChip({ attachment: a }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { filename, download_url } | { error }
  const [previewOpen, setPreviewOpen] = useState(false);
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

  if (a.kind === "image") {
    return (
      <a
        className="msg-image-attachment"
        href={`${api.base}/api/attachments/${a.id}/download`}
        target="_blank"
        rel="noopener noreferrer"
        title={a.name}
      >
        <img src={`${api.base}/api/attachments/${a.id}/download`} alt={a.name} loading="lazy" />
      </a>
    );
  }

  return (
    <div className="doc-chip-wrap">
      <span className="msg-attachment-chip" onClick={() => setPreviewOpen(true)} style={{ cursor: "pointer" }}>
        <Icon name={KIND_ICON[a.kind] || "paperclip"} size={14} /> {a.name}
        {editable && (
          <button
            className="doc-chip-edit-btn"
            onClick={(e) => { e.stopPropagation(); handleEdit(); }}
            disabled={busy}
            title="Edit this document"
          >
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
      {previewOpen && (
        <DocumentPreview attachmentId={a.id} filename={a.name} onClose={() => setPreviewOpen(false)} />
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
    call.args?.command || call.args?.path || call.args?.query || call.args?.url || call.args?.task ||
    call.args?.selector || (call.tool === "git" ? call.args?.op : "") ||
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
  const [comparing, setComparing] = useState(false);
  if (!siblings || siblings.length < 2) return null;
  const idx = siblings.findIndex((s) => s.id === activeId);
  const pos = idx >= 0 ? idx : 0;
  const go = (delta) => {
    const next = siblings[(pos + delta + siblings.length) % siblings.length];
    onSwitch?.(next.id);
  };
  return (
    <>
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
        <button onClick={() => setComparing(true)} title="Compare versions side by side" className="branch-switcher-compare">
          <Icon name="layers" size={12} />
        </button>
      </div>
      {comparing && (
        <RegenerationDiff
          siblings={siblings}
          initialLeftId={siblings[Math.max(0, pos - 1)].id}
          initialRightId={activeId}
          onClose={() => setComparing(false)}
        />
      )}
    </>
  );
}

function PlanCard({ plan, onDecision }) {
  return (
    <div className={`plan-card plan-card-${plan.status}`}>
      <div className="plan-card-header">
        <Icon name="layers" size={14} />
        <span>Proposed plan</span>
        {plan.status !== "pending" && (
          <span className={`plan-card-status plan-card-status-${plan.status}`}>
            {plan.status === "approved" ? "approved" : "rejected"}
          </span>
        )}
      </div>
      <pre className="plan-card-body">{plan.text}</pre>
      {plan.status === "pending" && (
        <div className="tool-call-actions">
          <button className="tool-call-approve-btn" onClick={() => onDecision?.(plan.id, true)}>
            <Icon name="check" size={13} /> Approve &amp; run
          </button>
          <button className="tool-call-deny-btn" onClick={() => onDecision?.(plan.id, false)}>
            <Icon name="x" size={13} /> Reject
          </button>
        </div>
      )}
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
  onPlanDecision,
  onDeleteMessage,
  siblings,
  onSwitchBranch,
  onOpenEditor,
  personas,
  onRunReverted,
}) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);
  const [undoingRun, setUndoingRun] = useState(false);
  const [previewSource, setPreviewSource] = useState(null);
  const [shared, setShared] = useState(false);
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

  const share = async () => {
    const text = message.content || "";
    // Prefer the native share sheet (mobile/some desktops); fall back to
    // copying so the button always does something useful.
    try {
      if (navigator.share) {
        await navigator.share({ text });
        return;
      }
    } catch {
      /* user dismissed the share sheet — treat as a no-op */
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setShared(true);
      setTimeout(() => setShared(false), 1500);
    } catch {
      /* clipboard blocked */
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
        className={`msg-bubble ${isUser ? "msg-bubble-user" : "msg-bubble-assistant"} ${
          !isUser && message.toolCalls?.length > 0 ? "msg-bubble-agent" : ""
        }`}
        data-role={!isUser ? message.route_role : undefined}
      >
        {!isUser && message.speaker_persona_id && (
          <div className="group-speaker-badge">
            {message.speakerIcon || personas?.find((p) => p.id === message.speaker_persona_id)?.icon || ""}{" "}
            {message.speakerName || personas?.find((p) => p.id === message.speaker_persona_id)?.name || "Bot"}
          </div>
        )}
        {!isUser && message.model && !message.speaker_persona_id && (
          <ModelBadge model={message.model} role={message.route_role} reason={message.route_reason} />
        )}

        {message.attachments?.length > 0 && (
          <div className="msg-attachments">
            {message.attachments.map((a) => (
              <DocumentChip key={a.id} attachment={a} />
            ))}
          </div>
        )}

        {!isUser && message.plan && (
          <PlanCard plan={message.plan} onDecision={onPlanDecision} />
        )}

        {!isUser && message.toolCalls?.length > 0 && (
          <div className="build-log">
            <div className="build-log-header">
              <Icon name="terminal" size={12} />
              <span>
                {message.toolCalls.length} step{message.toolCalls.length === 1 ? "" : "s"}
              </span>
              {message.toolCalls.some((c) => ["edit_file", "write_file"].includes(c.tool) && c.status === "done") && (
                <button
                  className="build-log-undo-all-btn"
                  disabled={undoingRun}
                  onClick={async () => {
                    if (!window.confirm("Undo every file edit from this run?")) return;
                    setUndoingRun(true);
                    try {
                      await api.revertRun(message.parent_id);
                      onRunReverted?.();
                    } finally {
                      setUndoingRun(false);
                    }
                  }}
                >
                  {undoingRun ? "Undoing…" : "Undo whole run"}
                </button>
              )}
            </div>
            <div className="tool-calls">
              {message.toolCalls.map((call) => (
                <ToolCallCard key={call.id} call={call} onApprove={onApproveTool} onDeny={onDenyTool} onRevert={onRevertTool} />
              ))}
            </div>
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
              <>
                <span className="thinking-dots" data-role={message.route_role} aria-label="Thinking">
                  <span />
                  <span />
                  <span />
                </span>
                <SlowReplyHint />
              </>
            ) : (
              <>
                {(() => {
                  const { trace, rest, thinking } = splitThinking(message.content);
                  return (
                    <>
                      {trace && <ThinkingTrace trace={trace} thinking={thinking} />}
                      <MarkdownRenderer content={rest} onOpenEditor={onOpenEditor} />
                    </>
                  );
                })()}
                {message.streaming && <span className="cursor-blink" data-role={message.route_role} />}
              </>
            )}
            {message.generatedImages?.length > 0 && (
              <div className="msg-generated-images">
                {message.generatedImages.map((src, i) => (
                  <a key={i} href={src} target="_blank" rel="noopener noreferrer">
                    <img src={src} alt="Generated" />
                  </a>
                ))}
              </div>
            )}
          </div>
        )}

        {!isUser && message.sources?.length > 0 && (
          <div className="msg-sources">
            {message.sources.map((s, i) =>
              s.url ? (
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
              ) : s.kind === "document" && s.attachment_id ? (
                <button
                  key={s.attachment_id + i}
                  className="msg-source-chip msg-source-chip-recall"
                  title={`Click to preview — used: "${s.text}"`}
                  onClick={() => setPreviewSource(s)}
                >
                  <Icon name="file-text" size={12} /> {s.source_id}
                </button>
              ) : (
                <span
                  key={(s.source_id || "") + i}
                  className="msg-source-chip msg-source-chip-recall"
                  title={s.text}
                >
                  <Icon name="layers" size={12} />{" "}
                  {s.kind === "folder" ? "watched folder" : "past conversation"}
                </span>
              )
            )}
          </div>
        )}
        {previewSource && (
          <DocumentPreview
            attachmentId={previewSource.attachment_id}
            filename={previewSource.source_id}
            highlightText={previewSource.text}
            onClose={() => setPreviewSource(null)}
          />
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
              {message.content && (
                <button onClick={share} title="Share (or copy)">
                  {shared ? <><Icon name="check" size={13} /> Copied</> : <><Icon name="share" size={13} /> Share</>}
                </button>
              )}
              {onDeleteMessage && (
                <button onClick={() => onDeleteMessage(message)} title="Delete this message" className="msg-action-danger">
                  <Icon name="trash" size={13} /> Delete
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