import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import MarkdownRenderer from "./MarkdownRenderer";
import Select from "./Select.jsx";

const MAX = 4;

function Stat({ label, value }) {
  return <span className="cmp-stat"><b>{value ?? "—"}</b>{label}</span>;
}

/** One prompt, two to four models, side by side: time to first word,
 * total time and speed, saved so you can come back and pick a winner. */
export default function ModelCompare({ onClose }) {
  const [models, setModels] = useState([]);
  const [picked, setPicked] = useState(["", ""]);
  const [prompt, setPrompt] = useState("");
  const [cols, setCols] = useState({});
  const [runId, setRunId] = useState(null);
  const [winner, setWinner] = useState(null);
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const abortRef = useRef(null);

  useEffect(() => {
    api.listModels().then((m) => {
      const names = m.filter((x) => !/embed/i.test(x.name)).map((x) => x.name);
      setModels(names);
      setPicked([names[0] || "", names[1] || ""]);
    }).catch(() => {});
    api.listCompares().then(setHistory).catch(() => {});
  }, []);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && !running && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, running]);

  const chosen = [...new Set(picked.filter(Boolean))];
  const run = async () => {
    if (chosen.length < 2 || !prompt.trim()) return;
    setError(""); setWinner(null); setRunId(null); setRunning(true);
    setCols(Object.fromEntries(chosen.map((m) => [m, { text: "", status: "waiting" }])));
    const ctl = new AbortController(); abortRef.current = ctl;
    await api.runCompare({ prompt, models: chosen }, (ev) => {
      if (ev.type === "compare_start") setRunId(ev.id);
      else if (ev.type === "token") setCols((c) => ({ ...c, [ev.model]: { ...c[ev.model], text: (c[ev.model]?.text || "") + ev.text, status: "running" } }));
      else if (ev.type === "model_done") setCols((c) => ({ ...c, [ev.model]: { ...ev, status: "done" } }));
      else if (ev.type === "model_error") setCols((c) => ({ ...c, [ev.model]: { ...c[ev.model], error: ev.error, status: "error" } }));
      else if (ev.type === "error") setError(ev.message);
    }, ctl.signal);
    setRunning(false);
    api.listCompares().then(setHistory).catch(() => {});
  };
  const pickWinner = async (m) => {
    const next = winner === m ? null : m;
    setWinner(next);
    if (runId) await api.setCompareWinner(runId, next).catch(() => {});
  };
  const openSaved = (h) => {
    setPrompt(h.prompt); setRunId(h.id); setWinner(h.winner);
    setPicked(h.results.map((r) => r.model).concat(["", ""]).slice(0, Math.max(2, h.results.length)));
    setCols(Object.fromEntries(h.results.map((r) => [r.model, { ...r, status: r.error ? "error" : "done" }])));
  };

  return createPortal(
    <div className="notes-overlay" onClick={() => !running && onClose()}>
      <div className="notes-modal cmp-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="cmp-title">
        <div className="notes-header">
          <span id="cmp-title"><Icon name="split" size={16} /> Compare models</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close" disabled={running}><Icon name="x" size={14} /></button>
        </div>
        <div className="cmp-setup">
          <div className="cmp-pickers">
            {picked.map((m, i) => (
              <div key={i} className="cmp-picker">
                <Select value={m} onChange={(e) => setPicked((p) => p.map((x, j) => (j === i ? e.target.value : x)))} aria-label={`Model ${i + 1}`}>
                  <option value="">Choose a model…</option>
                  {models.map((n) => <option key={n} value={n}>{n}</option>)}
                </Select>
                {picked.length > 2 && <button className="cstate-del" onClick={() => setPicked((p) => p.filter((_, j) => j !== i))} aria-label="Remove"><Icon name="x" size={12} /></button>}
              </div>
            ))}
            {picked.length < MAX && <button className="wf-btn" onClick={() => setPicked((p) => [...p, ""])}>+ Model</button>}
          </div>
          <div className="cmp-prompt">
            <textarea rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="One prompt for every model…"
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); }} />
            {running ? <button className="wf-btn" onClick={() => abortRef.current?.abort()}>Stop</button>
              : <button className="wf-btn primary" onClick={run} disabled={chosen.length < 2 || !prompt.trim()}>Compare</button>}
          </div>
          {error && <div className="cstate-error">{error}</div>}
        </div>
        <div className="cmp-grid" style={{ gridTemplateColumns: `repeat(${Math.max(2, Object.keys(cols).length || chosen.length)}, minmax(0, 1fr))` }}>
          {Object.keys(cols).length === 0 ? (
            <div className="cmp-empty">
              <p className="wf-muted">Pick two to four models and a prompt. Each answers at the same time; you see how fast each one starts, finishes and generates.</p>
              {history.length > 0 && (
                <ul className="cmp-history">
                  {history.slice(0, 8).map((h) => (
                    <li key={h.id}>
                      <button onClick={() => openSaved(h)}><strong>{h.prompt}</strong><em>{h.results.map((r) => r.model).join(" · ")}{h.winner ? ` — winner ${h.winner}` : ""}</em></button>
                      <button className="cstate-del" onClick={async () => { await api.deleteCompare(h.id); setHistory((x) => x.filter((y) => y.id !== h.id)); }} aria-label="Delete"><Icon name="trash" size={12} /></button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : Object.entries(cols).map(([m, c]) => (
            <section key={m} className={`cmp-col ${winner === m ? "is-winner" : ""}`}>
              <header>
                <strong title={m}>{m}</strong>
                {c.status === "done" && <button className={`cmp-win ${winner === m ? "is-on" : ""}`} onClick={() => pickWinner(m)}>{winner === m ? "★ Winner" : "☆ Pick"}</button>}
              </header>
              <div className="cmp-stats">
                <Stat label="first word" value={c.ttft_ms != null ? `${(c.ttft_ms / 1000).toFixed(2)}s` : null} />
                <Stat label="total" value={c.total_ms != null ? `${(c.total_ms / 1000).toFixed(1)}s` : null} />
                <Stat label="tok/s ≈" value={c.tps} />
              </div>
              <div className="cmp-body">
                {c.status === "waiting" && <p className="wf-muted">Loading the model…</p>}
                {c.error ? <div className="wf-alert error">{c.error}</div> : <div className="msg-content"><MarkdownRenderer content={c.text || ""} /></div>}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}
