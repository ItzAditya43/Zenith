import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";

const EXT_BY_LANG = {
  python: "py", javascript: "js", jsx: "jsx", typescript: "ts", tsx: "tsx",
  bash: "sh", shell: "sh", json: "json", html: "html", css: "css",
  yaml: "yaml", sql: "sql", rust: "rs", go: "go", java: "java", c: "c",
  cpp: "cpp", markdown: "md",
};

// Full HTML documents obviously get a preview; a bare snippet that just
// happens to contain a <script>/<style> tag (common when a model pastes a
// fragment) is also treated as previewable so "Open in editor" on that kind
// of block isn't a dead end.
function looksPreviewable(lang, text) {
  if (lang === "html") return true;
  if (lang === "javascript" || lang === "jsx") return true;
  return /<\/html>|<script[\s>]|<style[\s>]/i.test(text || "");
}

function buildPreviewDoc(text, lang) {
  const isFullDoc = /<!doctype html/i.test(text) || /<html[\s>]/i.test(text);
  if (isFullDoc) return text;
  if (lang === "javascript" || lang === "jsx") {
    return `<!doctype html>
<html>
  <head><meta charset="utf-8" /></head>
  <body>
    <script>
${text}
    <\/script>
  </body>
</html>`;
  }
  // A fragment with inline <script>/<style> but no <html> wrapper — wrap it
  // so it still renders as a document instead of being dropped verbatim
  // into srcdoc (which behaves inconsistently for partial markup).
  return `<!doctype html>
<html>
  <head><meta charset="utf-8" /></head>
  <body>
${text}
  </body>
</html>`;
}

// Pyodide is a ~10-30MB WASM runtime. Loading it from a public CDN would
// break Zenith's "nothing calls out except your own Ollama" guarantee, so
// it is never fetched remotely. Instead we look for locally vendored
// assets at /pyodide/pyodide.js (same origin, same pattern as the
// self-hosted fonts in main.jsx) and only load them lazily, on first Run.
// If a maintainer wants Python execution, they vendor the runtime once:
//   npm install pyodide   (in frontend/)
//   cp -r node_modules/pyodide/* public/pyodide/
// If those assets aren't present, the Run tab explains that clearly
// instead of silently falling back to a CDN.
const PYODIDE_SCRIPT_URL = "/pyodide/pyodide.js";
const PYODIDE_INDEX_URL = "/pyodide/";

function loadPyodideScript() {
  if (window.loadPyodide) return Promise.resolve(true);
  return new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = PYODIDE_SCRIPT_URL;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

/**
 * Artifacts-style side-by-side workspace: a code block pulled out of the
 * chat into its own live-editable pane, so you can tweak it without
 * re-prompting the model for every small change. Purely client-side —
 * "Send back" is how an edit re-enters the conversation.
 *
 * Alongside the plain code view, this panel can also show a sandboxed
 * live preview (HTML/CSS/JS) or run Python in-browser via Pyodide — both
 * additive, both entirely local, neither one changes the existing
 * copy/download/close/send-back behavior.
 */
export default function DocumentEditor({ doc, onClose, onSendBack }) {
  const [text, setText] = useState(doc.text);
  const [copied, setCopied] = useState(false);
  const dirty = text !== doc.text;

  const canPreview = looksPreviewable(doc.lang, doc.text);
  const canRun = doc.lang === "python";
  const [tab, setTab] = useState("code");

  // --- Live preview ---------------------------------------------------
  const [previewDoc, setPreviewDoc] = useState("");
  useEffect(() => {
    if (tab !== "preview" || !canPreview) return;
    const handle = setTimeout(() => {
      setPreviewDoc(buildPreviewDoc(text, doc.lang));
    }, 400);
    return () => clearTimeout(handle);
  }, [text, tab, canPreview, doc.lang]);

  // --- Python run via Pyodide ------------------------------------------
  const pyodideRef = useRef(null);
  const [pyStatus, setPyStatus] = useState("idle"); // idle | loading | running | done
  const [pyMissing, setPyMissing] = useState(false);
  const [pyOutput, setPyOutput] = useState("");

  const runPython = async () => {
    setPyOutput("");
    setPyMissing(false);
    try {
      if (!pyodideRef.current) {
        setPyStatus("loading");
        const ok = await loadPyodideScript();
        if (!ok || !window.loadPyodide) {
          setPyMissing(true);
          setPyStatus("idle");
          return;
        }
        pyodideRef.current = await window.loadPyodide({ indexURL: PYODIDE_INDEX_URL });
      }
      const pyodide = pyodideRef.current;
      let buffer = "";
      pyodide.setStdout({ batched: (s) => { buffer += s + "\n"; } });
      pyodide.setStderr({ batched: (s) => { buffer += s + "\n"; } });

      setPyStatus("running");
      let result;
      try {
        result = await pyodide.runPythonAsync(text);
      } catch (err) {
        // Python tracebacks render as-is — don't swallow or reformat them.
        buffer += String(err);
        setPyOutput(buffer);
        setPyStatus("done");
        return;
      }
      if (result !== undefined && result !== null) {
        buffer += String(result);
      }
      setPyOutput(buffer);
      setPyStatus("done");
    } catch (err) {
      setPyOutput((prev) => `${prev}\n${String(err)}`);
      setPyStatus("done");
    }
  };

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

      {(canPreview || canRun) && (
        <div className="doc-editor-tabs" role="tablist">
          <button
            role="tab"
            aria-selected={tab === "code"}
            className={`doc-editor-tab ${tab === "code" ? "doc-editor-tab-active" : ""}`}
            onClick={() => setTab("code")}
          >
            <Icon name="pencil" size={13} /> Code
          </button>
          {canPreview && (
            <button
              role="tab"
              aria-selected={tab === "preview"}
              className={`doc-editor-tab ${tab === "preview" ? "doc-editor-tab-active" : ""}`}
              onClick={() => setTab("preview")}
            >
              <Icon name="layers" size={13} /> Preview
            </button>
          )}
          {canRun && (
            <button
              role="tab"
              aria-selected={tab === "run"}
              className={`doc-editor-tab ${tab === "run" ? "doc-editor-tab-active" : ""}`}
              onClick={() => setTab("run")}
            >
              <Icon name="terminal" size={13} /> Run
            </button>
          )}
        </div>
      )}

      {tab === "code" && (
        <textarea
          className="doc-editor-textarea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
        />
      )}

      {tab === "preview" && canPreview && (
        <iframe
          className="doc-editor-preview-frame"
          title="Live preview"
          srcDoc={previewDoc}
          sandbox="allow-scripts"
        />
      )}

      {tab === "run" && canRun && (
        <div className="doc-editor-run-panel">
          <div className="doc-editor-run-toolbar">
            <button
              className="settings-btn-primary"
              onClick={runPython}
              disabled={pyStatus === "loading" || pyStatus === "running"}
            >
              <Icon name="terminal" size={13} />{" "}
              {pyStatus === "loading" ? "Loading Pyodide…" : pyStatus === "running" ? "Running…" : "Run"}
            </button>
          </div>
          {pyMissing ? (
            <div className="doc-editor-run-missing">
              <Icon name="info" size={14} />
              <span>
                Python execution needs the Pyodide runtime, which isn't bundled by default
                (it's a large WASM download and would otherwise require calling out to a
                CDN). To enable it, a maintainer can vendor it locally: run{" "}
                <code>npm install pyodide</code> in <code>frontend/</code>, then copy{" "}
                <code>node_modules/pyodide/*</code> into <code>frontend/public/pyodide/</code>{" "}
                so it's served same-origin from <code>/pyodide/</code>.
              </span>
            </div>
          ) : (
            <pre className="doc-editor-run-output">{pyOutput || (pyStatus === "idle" ? "" : "…")}</pre>
          )}
        </div>
      )}

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
