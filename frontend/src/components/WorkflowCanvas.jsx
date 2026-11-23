import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  addEdge, Background, BackgroundVariant, Controls, Handle, MarkerType, Position,
  ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "../lib/api";
import { confirmDialog } from "../lib/dialogs";
import Icon from "./Icon.jsx";
import Select from "./Select.jsx";

/** Visual workflows: wire models, memory, web search and human review
 * together on a canvas, run it, and watch each step happen live. */

const KINDS = {
  input: { label: "Input", icon: "message-circle", tone: "ember", hint: "What the run starts with", out: true, inn: false },
  agent: { label: "Agent", icon: "bot", tone: "violet", hint: "A model with its own instructions", out: true, inn: true },
  memory: { label: "Memory", icon: "layers", tone: "sky", hint: "Recalls what Zenith remembers", out: true, inn: true },
  web: { label: "Web search", icon: "globe", tone: "teal", hint: "Searches the web (goes online)", out: true, inn: true },
  review: { label: "Human review", icon: "check-circle", tone: "amber", hint: "Pauses until you approve", out: true, inn: true },
  output: { label: "Output", icon: "send", tone: "ember", hint: "The final result", out: false, inn: true },
};

const uid = () => Math.random().toString(36).slice(2, 9);

function WFNode({ type, data, selected }) {
  const k = KINDS[type];
  const status = data.status || "idle";
  return (
    <div className={`wf-node tone-${k.tone} is-${status} ${selected ? "is-selected" : ""}`}>
      {k.inn && <Handle type="target" position={Position.Left} />}
      <span className="wf-node-ico"><Icon name={k.icon} size={15} /></span>
      <div className="wf-node-text">
        <strong>{data.label || k.label}</strong>
        <span>{status === "running" ? "Working…" : status === "waiting" ? "Needs your OK" : status === "done" ? `Done${data.ms ? ` · ${(data.ms / 1000).toFixed(1)}s` : ""}` : status === "error" ? "Failed" : status === "skipped" ? "Skipped" : k.hint}</span>
      </div>
      {status === "running" && <i className="wf-spin" />}
      {k.out && <Handle type="source" position={Position.Right} />}
    </div>
  );
}
const nodeTypes = Object.fromEntries(Object.keys(KINDS).map((t) => [t, WFNode]));

const starter = () => ({
  nodes: [
    { id: "n-in", type: "input", position: { x: 0, y: 150 }, data: { label: "Question" } },
    { id: "n-mem", type: "memory", position: { x: 280, y: 20 }, data: { label: "Memory" } },
    { id: "n-web", type: "web", position: { x: 280, y: 280 }, data: { label: "Web search" } },
    { id: "n-ag", type: "agent", position: { x: 560, y: 150 }, data: { label: "Researcher", model: "", prompt: "Answer the question using the memory and web results provided. Be concise and say where each fact came from." } },
    { id: "n-rev", type: "review", position: { x: 840, y: 150 }, data: { label: "Your review" } },
    { id: "n-out", type: "output", position: { x: 1100, y: 150 }, data: { label: "Answer" } },
  ],
  edges: [["n-in", "n-mem"], ["n-in", "n-web"], ["n-mem", "n-ag"], ["n-web", "n-ag"], ["n-ag", "n-rev"], ["n-rev", "n-out"]].map(([a, b]) => ({ id: `${a}-${b}`, source: a, target: b })),
});

const edgeDefaults = { animated: false, markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 } };

function Inner({ onClose }) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [flows, setFlows] = useState([]);
  const [wid, setWid] = useState(null);
  const [name, setName] = useState("Untitled workflow");
  const [selected, setSelected] = useState(null);
  const [models, setModels] = useState([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [trace, setTrace] = useState([]);
  const [outputs, setOutputs] = useState({});
  const [review, setReview] = useState(null);
  const [runId, setRunId] = useState(null);
  const [final, setFinal] = useState(null);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const abortRef = useRef(null);
  const wrapRef = useRef(null);
  const { screenToFlowPosition, fitView } = useReactFlow();

  const load = useCallback((flow) => {
    setWid(flow?.id ?? null);
    setName(flow?.name ?? "Untitled workflow");
    const g = flow?.graph ?? starter();
    setNodes(g.nodes.map((n) => ({ ...n, data: { ...n.data, status: "idle" } })));
    setEdges(g.edges.map((e) => ({ ...e, ...edgeDefaults })));
    setSelected(null); setTrace([]); setOutputs({}); setReview(null); setFinal(null); setError(""); setDirty(false);
    setTimeout(() => fitView({ padding: 0.1, maxZoom: 1.1, duration: 300 }), 50);
  }, [setNodes, setEdges, fitView]);

  useEffect(() => {
    api.listWorkflows().then((f) => { setFlows(f); load(f[0] ?? null); }).catch(() => load(null));
    api.listModels().then((m) => setModels(m.map((x) => x.name))).catch(() => {});
  }, [load]);

  const graph = useCallback(() => ({
    nodes: nodes.map((n) => ({ id: n.id, type: n.type, position: n.position, data: { label: n.data.label, model: n.data.model, prompt: n.data.prompt, query: n.data.query } })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  }), [nodes, edges]);

  const save = async () => {
    try {
      const saved = await api.saveWorkflow({ id: wid, name: name.trim() || "Untitled workflow", graph: graph() });
      setWid(saved.id); setDirty(false); setError("");
      setFlows(await api.listWorkflows());
    } catch (e) { setError(e.message); }
  };

  const remove = async () => {
    if (!wid) return load(null);
    if (!(await confirmDialog({ title: "Delete this workflow?", message: "Its run history goes with it.", confirmLabel: "Delete", danger: true }))) return;
    await api.deleteWorkflow(wid);
    const f = await api.listWorkflows();
    setFlows(f); load(f[0] ?? null);
  };

  const onConnect = useCallback((c) => { setEdges((es) => addEdge({ ...c, ...edgeDefaults }, es)); setDirty(true); }, [setEdges]);

  const addNode = (type, pos) => {
    const p = pos ?? { x: 120 + Math.random() * 160, y: 80 + Math.random() * 160 };
    const id = `n-${uid()}`;
    setNodes((ns) => [...ns, { id, type, position: p, data: { label: KINDS[type].label, status: "idle" } }]);
    setSelected(id); setDirty(true);
  };
  const onDrop = (e) => {
    e.preventDefault();
    const t = e.dataTransfer.getData("application/zenith-node");
    if (KINDS[t]) addNode(t, screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };

  const patch = (id, d) => { setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...d } } : n))); setDirty(true); };
  const setStatus = (id, status, extra = {}) => setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, status, ...extra } } : n)));

  const run = async () => {
    setError(""); setTrace([]); setOutputs({}); setFinal(null); setReview(null);
    setNodes((ns) => ns.map((n) => ({ ...n, data: { ...n.data, status: "idle", ms: undefined } })));
    setEdges((es) => es.map((e) => ({ ...e, animated: false })));
    setRunning(true);
    const ctl = new AbortController(); abortRef.current = ctl;
    const label = (id) => nodes.find((n) => n.id === id)?.data.label || id;
    await api.runWorkflow({ graph: graph(), input, workflow_id: wid }, (ev) => {
      if (ev.type === "run_start") setRunId(ev.run_id);
      else if (ev.type === "node_start") {
        setStatus(ev.node, "running");
        setEdges((es) => es.map((e) => (e.target === ev.node ? { ...e, animated: true } : e)));
        setTrace((t) => [...t, { id: `${ev.node}-s`, kind: "start", text: `${label(ev.node)} started` }]);
      } else if (ev.type === "token") setOutputs((o) => ({ ...o, [ev.node]: (o[ev.node] || "") + ev.text }));
      else if (ev.type === "review_request") {
        setStatus(ev.node, "waiting"); setReview({ node: ev.node, preview: ev.preview });
        setTrace((t) => [...t, { id: `${ev.node}-r`, kind: "wait", text: `${label(ev.node)} is waiting for you` }]);
      } else if (ev.type === "node_done") {
        setStatus(ev.node, "done", { ms: ev.ms });
        setEdges((es) => es.map((e) => (e.target === ev.node ? { ...e, animated: false } : e)));
        setOutputs((o) => ({ ...o, [ev.node]: ev.output }));
        setTrace((t) => [...t, { id: `${ev.node}-d`, kind: "done", text: `${label(ev.node)} finished`, ms: ev.ms }]);
      } else if (ev.type === "node_error") {
        setStatus(ev.node, "error");
        setTrace((t) => [...t, { id: `${ev.node}-e`, kind: "error", text: `${label(ev.node)}: ${ev.error}` }]);
      } else if (ev.type === "node_skipped") {
        setStatus(ev.node, "skipped");
        setTrace((t) => [...t, { id: `${ev.node}-k`, kind: "skip", text: `${label(ev.node)} skipped` }]);
      } else if (ev.type === "run_error" || ev.type === "error") setError(ev.error || ev.message || "Something went wrong.");
      else if (ev.type === "run_done") { setFinal({ status: ev.status, output: ev.output }); setReview(null); }
    }, ctl.signal);
    setEdges((es) => es.map((e) => ({ ...e, animated: false })));
    setRunning(false);
  };
  const stop = () => { abortRef.current?.abort(); setRunning(false); setReview(null); };
  const answer = async (approve) => {
    const r = review; setReview(null);
    try { await api.reviewWorkflow(runId, r.node, approve); } catch (e) { setError(e.message); }
  };

  const sel = nodes.find((n) => n.id === selected);
  const modelOptions = useMemo(() => models, [models]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !running) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, running]);

  return (
    <div className="wf-overlay" role="dialog" aria-modal="true" aria-label="Workflows">
      <div className="wf-shell">
        <header className="wf-top">
          <div className="wf-title">
            <span className="wf-title-ico"><Icon name="git-branch" size={16} /></span>
            <input className="wf-name" value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} aria-label="Workflow name" />
            {dirty && <span className="wf-dirty">Unsaved</span>}
          </div>
          <div className="wf-top-actions">
            <Select value={wid ?? ""} onChange={(e) => { const f = flows.find((x) => x.id === e.target.value); load(f ?? null); }} aria-label="Open workflow">
              <option value="">{wid ? "New workflow" : "Starter workflow"}</option>
              {flows.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </Select>
            <button className="wf-btn" onClick={() => load(null)} disabled={running}>New</button>
            <button className="wf-btn" onClick={save} disabled={running}>Save</button>
            <button className="wf-btn danger" onClick={remove} disabled={running} aria-label="Delete workflow"><Icon name="trash" size={14} /></button>
            <button className="wf-close" onClick={onClose} aria-label="Close"><Icon name="x" size={16} /></button>
          </div>
        </header>

        <div className="wf-body">
          <aside className="wf-lib">
            <h3>Components</h3>
            {Object.entries(KINDS).map(([t, k]) => (
              <button key={t} className={`wf-lib-item tone-${k.tone}`} draggable
                onDragStart={(e) => { e.dataTransfer.setData("application/zenith-node", t); e.dataTransfer.effectAllowed = "move"; }}
                onClick={() => addNode(t)} title="Click to add, or drag onto the canvas">
                <span className="wf-node-ico"><Icon name={k.icon} size={14} /></span>
                <span><strong>{k.label}</strong><em>{k.hint}</em></span>
              </button>
            ))}
            <p className="wf-tip">Drag a component onto the canvas, then pull from one node's right dot to another's left dot.</p>
          </aside>

          <div className="wf-canvas" ref={wrapRef} onDrop={onDrop} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}>
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes}
              onNodesChange={(c) => { onNodesChange(c); if (c.some((x) => x.type === "position" || x.type === "remove")) setDirty(true); }}
              onEdgesChange={(c) => { onEdgesChange(c); if (c.some((x) => x.type === "remove")) setDirty(true); }}
              onConnect={onConnect} onNodeClick={(_, n) => setSelected(n.id)} onPaneClick={() => setSelected(null)}
              fitView fitViewOptions={{ padding: 0.1, maxZoom: 1.1 }} proOptions={{ hideAttribution: true }} deleteKeyCode={["Backspace", "Delete"]} minZoom={0.3}>
              <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} />
              <Controls showInteractive={false} />
            </ReactFlow>
            <div className="wf-runbar">
              <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="What should this workflow work on?" disabled={running}
                onKeyDown={(e) => { if (e.key === "Enter" && !running) run(); }} aria-label="Workflow input" />
              {running ? <button className="wf-run stop" onClick={stop}><Icon name="square" size={13} /> Stop</button>
                : <button className="wf-run" onClick={run}><Icon name="send" size={13} /> Run</button>}
            </div>
          </div>

          <aside className="wf-side">
            <section>
              <h3>Configuration</h3>
              {!sel ? <p className="wf-muted">Select a node to set it up.</p> : (
                <div className="wf-form">
                  <label>Name<input value={sel.data.label || ""} onChange={(e) => patch(sel.id, { label: e.target.value })} /></label>
                  {sel.type === "agent" && (<>
                    <label>Model
                      <Select value={sel.data.model || ""} onChange={(e) => patch(sel.id, { model: e.target.value })}>
                        <option value="">Automatic</option>
                        {modelOptions.map((m) => <option key={m} value={m}>{m}</option>)}
                      </Select>
                    </label>
                    <label>Instructions<textarea rows={6} value={sel.data.prompt || ""} placeholder="What should this agent do with what it receives?" onChange={(e) => patch(sel.id, { prompt: e.target.value })} /></label>
                  </>)}
                  {sel.type === "web" && <label>Search for<input value={sel.data.query || ""} placeholder="Leave blank to search the input" onChange={(e) => patch(sel.id, { query: e.target.value })} /></label>}
                  {sel.type === "review" && <p className="wf-muted">The run stops here until you approve. Rejecting ends this branch.</p>}
                  {sel.type === "memory" && <p className="wf-muted">Looks up what Zenith remembers that relates to the input.</p>}
                  <button className="wf-btn danger" onClick={() => { setNodes((ns) => ns.filter((n) => n.id !== sel.id)); setEdges((es) => es.filter((e) => e.source !== sel.id && e.target !== sel.id)); setSelected(null); setDirty(true); }}>Remove node</button>
                </div>
              )}
            </section>

            <section className="wf-trace">
              <h3>Live trace {running && <i className="wf-live" />}</h3>
              {error && <div className="wf-alert error">{error}</div>}
              {review && (
                <div className="wf-alert review">
                  <strong>Review needed</strong>
                  <p>{review.preview || "Nothing to show."}</p>
                  <div><button className="wf-btn primary" onClick={() => answer(true)}>Approve</button><button className="wf-btn" onClick={() => answer(false)}>Reject</button></div>
                </div>
              )}
              {trace.length === 0 && !error && <p className="wf-muted">Run the workflow and every step shows up here as it happens.</p>}
              <ol className="wf-steps">
                {trace.map((t) => <li key={t.id} className={`k-${t.kind}`}><i />{t.text}{t.ms ? <em>{(t.ms / 1000).toFixed(1)}s</em> : null}</li>)}
              </ol>
              {sel && outputs[sel.id] && (<><h4>{sel.data.label || "Node"} output</h4><pre className="wf-out">{outputs[sel.id]}</pre></>)}
              {final && (<><h4>Result · {final.status}</h4><pre className="wf-out final">{final.output || "No output."}</pre></>)}
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}

export default function WorkflowCanvas({ onClose }) {
  return <ReactFlowProvider><Inner onClose={onClose} /></ReactFlowProvider>;
}
