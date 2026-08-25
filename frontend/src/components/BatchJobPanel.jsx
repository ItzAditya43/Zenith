import { useRef, useState, useEffect } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

/**
 * Standalone batch-job overlay: point it at a folder, give it a prompt
 * template and a model, and it runs that prompt against every matching
 * file in the folder (one level deep, non-recursive — see
 * batch_service.py), streaming a result per file as it completes.
 *
 * Distinct from the folder-watcher (RAG indexing, reactive recall) —
 * this is an explicit, one-shot "summarize every file in this folder"
 * operation. Not wired into App.jsx/SettingsPanel.jsx yet; a later
 * integration pass adds the entry point that opens this panel.
 *
 * Mirrors HealthPanel.jsx's overlay/dialog structure and CSS classes.
 */
export default function BatchJobPanel({ onClose }) {
  const [folderPath, setFolderPath] = useState("");
  const [promptTemplate, setPromptTemplate] = useState("");
  const [extensions, setExtensions] = useState("");
  const [model, setModel] = useState("");
  const [models, setModels] = useState([]);
  const [modelsError, setModelsError] = useState(null);

  const [running, setRunning] = useState(false);
  const [results, setResults] = useState([]);
  const [runError, setRunError] = useState(null);
  const [expanded, setExpanded] = useState({});

  const abortRef = useRef(null);

  useEffect(() => {
    api
      .listModels()
      .then((list) => {
        setModels(list || []);
        if (list && list.length > 0) setModel((prev) => prev || list[0].name);
      })
      .catch((err) => setModelsError(err.message || "Failed to load models."));
  }, []);

  const canRun = folderPath.trim() && promptTemplate.trim() && model && !running;

  const run = () => {
    if (!canRun) return;
    setResults([]);
    setRunError(null);
    setRunning(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const extList = extensions
      .split(",")
      .map((e) => e.trim())
      .filter(Boolean);

    api
      .runBatch(
        {
          folderPath: folderPath.trim(),
          promptTemplate: promptTemplate.trim(),
          model,
          extensions: extList.length > 0 ? extList : null,
        },
        (ev) => {
          if (ev.status === "done" && !ev.file) {
            // final terminal frame, nothing to render
            return;
          }
          if (ev.status === "error" && !ev.file) {
            setRunError(ev.error || "Batch job failed.");
            return;
          }
          setResults((prev) => [...prev, ev]);
        },
        controller.signal
      )
      .finally(() => {
        setRunning(false);
        abortRef.current = null;
      });
  };

  const cancel = () => {
    if (abortRef.current) abortRef.current.abort();
    setRunning(false);
  };

  const toggleExpanded = (idx) => {
    setExpanded((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div
        className="calendar-modal"
        style={{ width: "min(640px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="batch-panel-title"
      >
        <div className="calendar-header">
          <span id="batch-panel-title">Batch job</span>
          <div style={{ display: "flex", gap: "var(--space-1)" }}>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>

        <div style={{ padding: "var(--space-3) var(--space-4)", maxHeight: "75vh", overflowY: "auto" }}>
          <p className="conversation-empty" style={{ marginTop: 0 }}>
            Run one prompt against every file in a folder — e.g. "summarize each of these
            meeting notes" — and see the result per file as it's produced.
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            <label>
              Folder path
              <input
                type="text"
                value={folderPath}
                onChange={(e) => setFolderPath(e.target.value)}
                placeholder="/home/you/notes"
                disabled={running}
                style={{ width: "100%" }}
              />
            </label>

            <label>
              Prompt template
              <textarea
                value={promptTemplate}
                onChange={(e) => setPromptTemplate(e.target.value)}
                placeholder="Summarize this note in one sentence."
                rows={3}
                disabled={running}
                style={{ width: "100%" }}
              />
            </label>

            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              <label style={{ flex: 1 }}>
                Model
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  disabled={running || models.length === 0}
                  style={{ width: "100%" }}
                >
                  {models.length === 0 && <option value="">No models installed</option>}
                  {models.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </label>

              <label style={{ flex: 1 }}>
                Extensions (optional)
                <input
                  type="text"
                  value={extensions}
                  onChange={(e) => setExtensions(e.target.value)}
                  placeholder=".txt,.md"
                  disabled={running}
                  style={{ width: "100%" }}
                />
              </label>
            </div>

            {modelsError && <p className="conversation-empty">{modelsError}</p>}

            <div style={{ display: "flex", gap: "var(--space-2)" }}>
              {!running ? (
                <button className="btn btn-primary" onClick={run} disabled={!canRun}>
                  Run
                </button>
              ) : (
                <button className="btn" onClick={cancel}>
                  Cancel
                </button>
              )}
              {running && <span className="conversation-empty">Running…</span>}
            </div>

            {runError && <p className="conversation-empty">{runError}</p>}

            {results.length > 0 && (
              <div className="health-list">
                {results.map((r, idx) => (
                  <div key={`${r.file}-${idx}`} className="health-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
                    <div
                      className="health-row-main"
                      style={{ cursor: r.status === "done" ? "pointer" : "default", justifyContent: "space-between" }}
                      onClick={() => r.status === "done" && toggleExpanded(idx)}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
                        <span className={`health-dot ${r.status === "done" ? "is-ok" : "is-down"}`} aria-hidden="true" />
                        <span className="health-row-label">{r.file}</span>
                      </span>
                      {r.status === "done" && (
                        <Icon name={expanded[idx] ? "chevron-up" : "chevron-down"} size={14} />
                      )}
                    </div>
                    {r.status === "error" && (
                      <div className="health-row-detail">{r.error}</div>
                    )}
                    {r.status === "done" && expanded[idx] && (
                      <div className="health-row-detail" style={{ whiteSpace: "pre-wrap" }}>
                        {r.result}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
