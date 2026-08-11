import { useState } from "react";
import Icon from "./Icon.jsx";

const EXT_BY_LANG = {
  python: "py", javascript: "js", jsx: "jsx", typescript: "ts", tsx: "tsx",
  bash: "sh", shell: "sh", json: "json", html: "html", css: "css",
  yaml: "yaml", sql: "sql", rust: "rs", go: "go", java: "java", c: "c",
  cpp: "cpp", markdown: "md",
};

/**
 * Artifacts-style side-by-side workspace: a code block pulled out of the
 * chat into its own live-editable pane, so you can tweak it without
 * re-prompting the model for every small change. Purely client-side —
 * "Send back" is how an edit re-enters the conversation.
 */
export default function DocumentEditor({ doc, onClose, onSendBack }) {
  const [text, setText] = useState(doc.text);
  const [copied, setCopied] = useState(false);
  const dirty = text !== doc.text;

  const copy = () => {
    navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const download = () => {
    const ext = EXT_BY_LANG[doc.lang] || "txt";
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `document.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="doc-editor-panel" role="dialog" aria-modal="true" aria-labelledby="doc-editor-title">
      <div className="doc-editor-header">
        <span className="doc-editor-lang" id="doc-editor-title">
          <Icon name="pencil" size={13} /> {doc.lang}
          {dirty && <span className="doc-editor-dirty-dot" title="Unsaved changes" />}
        </span>
        <div className="doc-editor-actions">
          <button className="icon-btn" onClick={copy} title="Copy" aria-label={copied ? "Copied" : "Copy"}>
            <Icon name={copied ? "check" : "copy"} size={14} />
          </button>
          <button className="icon-btn" onClick={download} title="Download" aria-label="Download">
            <Icon name="download" size={14} />
          </button>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
      </div>
      <textarea
        className="doc-editor-textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
      />
      {dirty && (
        <div className="doc-editor-footer">
          <button
            className="settings-btn-primary"
            onClick={() => onSendBack(text, doc.lang)}
          >
            Send edited version to chat
          </button>
        </div>
      )}
    </div>
  );
}
