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
  if (lang === "javascript" || lang === "jsx" || lang === "tsx") return true;
  return /<\/html>|<script[\s>]|<style[\s>]/i.test(text || "");
}

const JSX_LANGS = new Set(["jsx", "tsx"]);

// The preview iframe's React runtime — an IIFE that sets window.React /
// window.ReactDOM, built automatically at dev/build time from the React
// version already in package.json (see scripts/build-preview-runtime.mjs
// and the Vite plugin in vite.config.js). Self-hosted, same-origin, no CDN,
// no manual vendoring step required.
const PREVIEW_REACT_RUNTIME_URL = "/preview-runtime/react-runtime.js";

function buildPreviewDoc(text, lang, transformedJs, transformError) {
  const isFullDoc = /<!doctype html/i.test(text) || /<html[\s>]/i.test(text);
  if (isFullDoc) return text;

  if (JSX_LANGS.has(lang)) {
    if (transformError) {
      // Same spirit as Python tracebacks in the Run tab: show the error
      // as-is rather than leaving a blank white iframe with no explanation.
      const escaped = String(transformError)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;");
      return `<!doctype html>
<html>
  <head><meta charset="utf-8" /></head>
  <body>
    <pre style="white-space:pre-wrap;font-family:monospace;color:#c0392b;padding:12px;margin:0;">${escaped}</pre>
  </body>
</html>`;
    }
    if (transformedJs == null) {
      // Transform hasn't run yet (still loading esbuild-wasm, or missing).
      return `<!doctype html>
<html>
  <head><meta charset="utf-8" /></head>
  <body></body>
</html>`;
    }
    return `<!doctype html>
<html>
  <head><meta charset="utf-8" /></head>
  <body>
    <div id="root"></div>
    <script src="${PREVIEW_REACT_RUNTIME_URL}"><\/script>
    <script>
      try {
${transformedJs}
      } catch (err) {
        document.body.innerHTML = '<pre style="white-space:pre-wrap;font-family:monospace;color:#c0392b;padding:12px;margin:0;">' + String(err && err.stack || err) + '<\\/pre>';
      }
    <\/script>
  </body>
</html>`;
  }

  if (lang === "javascript") {
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

// esbuild-wasm's JS wrapper is small, but its .wasm binary is ~14MB —
// close enough to Pyodide's size class that it gets the exact same
// treatment: it is bundled as a real npm dependency (so no manual vendoring
// step is needed, unlike Pyodide) but the wasm binary itself is only ever
// fetched same-origin, lazily, on first use of a JSX/TSX preview — never
// from a CDN. Vite's `?url` asset handling copies the .wasm into the build
// output automatically; nothing calls out anywhere else.
let esbuildInitPromise = null;
async function ensureEsbuildInitialized() {
  if (!esbuildInitPromise) {
    esbuildInitPromise = (async () => {
      const [esbuild, { default: wasmURL }] = await Promise.all([
        import("esbuild-wasm"),
        import("esbuild-wasm/esbuild.wasm?url"),
      ]);
      await esbuild.initialize({ wasmURL });
      return esbuild;
    })();
  }
  return esbuildInitPromise;
}

async function transformJsx(text, lang) {
  const esbuild = await ensureEsbuildInitialized();
  const loader = lang === "tsx" ? "tsx" : "jsx";
  const result = await esbuild.transform(text, {
    loader,
    // Classic runtime: output is plain React.createElement(...) calls,
    // which only need the window.React / window.ReactDOM globals from the
    // vendored runtime above — no ESM import resolution needed inside the
    // sandboxed iframe (the "automatic" runtime would emit
    // `import {jsx} from "react/jsx-runtime"`, which a plain <script> tag
    // in srcDoc can't resolve).
    jsx: "transform",
    jsxFactory: "React.createElement",
    jsxFragment: "React.Fragment",
  });
  return result.code;
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
  const isJsxLang = JSX_LANGS.has(doc.lang);
  useEffect(() => {
    if (tab !== "preview" || !canPreview) return;
    // esbuild-wasm's transform is fast once initialized; a shorter debounce
    // for jsx/tsx reads better without hammering it on every keystroke.
    const delay = isJsxLang ? 250 : 400;
    let cancelled = false;
    const handle = setTimeout(() => {
      if (!isJsxLang) {
        setPreviewDoc(buildPreviewDoc(text, doc.lang));
        return;
      }
      transformJsx(text, doc.lang)
        .then((js) => {
          if (!cancelled) setPreviewDoc(buildPreviewDoc(text, doc.lang, js, null));
        })
        .catch((err) => {
          if (cancelled) return;
          // esbuild transform failures carry a structured `.errors` array
          // with readable location info; fall back to `.message`/String().
          const detail = Array.isArray(err?.errors) && err.errors.length
            ? err.errors.map((e) => e.text + (e.location ? ` (line ${e.location.line})` : "")).join("\n")
            : (err && err.message) || String(err);
          setPreviewDoc(buildPreviewDoc(text, doc.lang, null, detail));
        });
    }, delay);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [text, tab, canPreview, doc.lang, isJsxLang]);

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
