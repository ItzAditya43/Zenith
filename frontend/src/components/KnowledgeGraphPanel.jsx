import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { openMemoryBrowser } from "../lib/uiEvents.js";
import DocumentPreview from "./DocumentPreview.jsx";
import Icon from "./Icon.jsx";

const TYPES = [
  { type: "project", label: "Projects", one: "Project", icon: "folder" },
  { type: "conversation", label: "Chats", one: "Chat", icon: "message-circle" },
  { type: "memory", label: "Memories", one: "Memory", icon: "layers" },
  { type: "document", label: "Documents", one: "Document", icon: "file-text" },
];
const EDGE_LABEL = { in_project: "in project", extracted_from: "learned from", scoped_to: "scoped to", attached_to: "attached to" };
const ROW = 30, COL = 270, TOP = 16;

/** What's connected to what across chats, projects, memories and
 * documents — built only from real links already stored. Search and
 * filter it, pick anything to see its connections, and open it. */
export default function KnowledgeGraphPanel({ onClose, onOpenConversation }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(new Set(TYPES.map((t) => t.type)));
  const [connectedOnly, setConnectedOnly] = useState(false);
  const [sel, setSel] = useState(null);
  const [hover, setHover] = useState(null);
  const [preview, setPreview] = useState(null);

  useEffect(() => { api.getKnowledgeGraph().then(setData).catch((e) => setError(e.message)); }, []);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape" && !preview) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, preview]);

  const { byId, neighbors } = useMemo(() => {
    const byId = {}, neighbors = {};
    for (const n of data?.nodes || []) { byId[n.id] = n; neighbors[n.id] = []; }
    for (const e of data?.edges || []) {
      if (!byId[e.from] || !byId[e.to]) continue;
      neighbors[e.from].push({ id: e.to, kind: e.kind, dir: "out" });
      neighbors[e.to].push({ id: e.from, kind: e.kind, dir: "in" });
    }
    return { byId, neighbors };
  }, [data]);

  const visible = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    const match = (n) => !needle || n.label.toLowerCase().includes(needle);
    const hits = new Set(data.nodes.filter((n) => shown.has(n.type) && match(n)).map((n) => n.id));
    // A search also keeps what the hits connect to, so context isn't lost.
    if (needle) for (const id of [...hits]) for (const nb of neighbors[id]) if (shown.has(byId[nb.id].type)) hits.add(nb.id);
    return data.nodes.filter((n) => hits.has(n.id) && (!connectedOnly || neighbors[n.id].length));
  }, [data, q, shown, connectedOnly, neighbors, byId]);

  const layout = useMemo(() => {
    const cols = TYPES.filter((t) => shown.has(t.type));
    const pos = {};
    let maxRows = 1;
    cols.forEach((c, ci) => {
      const items = visible.filter((n) => n.type === c.type);
      maxRows = Math.max(maxRows, items.length);
      items.forEach((n, ri) => { pos[n.id] = { x: ci * COL + 14, y: TOP + ri * ROW }; });
    });
    return { cols, pos, width: Math.max(cols.length * COL, 300), height: TOP + maxRows * ROW + 20 };
  }, [visible, shown]);

  const focus = hover || sel;
  const lit = focus ? new Set([focus, ...(neighbors[focus] || []).map((n) => n.id)]) : null;
  const node = sel ? byId[sel] : null;
  const rawId = (id) => id.slice(id.indexOf(":") + 1);
  const open = (n) => {
    if (n.type === "conversation") { onOpenConversation?.(rawId(n.id)); onClose(); }
    else if (n.type === "memory") { onClose(); openMemoryBrowser(rawId(n.id)); }
    else if (n.type === "document") setPreview({ id: rawId(n.id), name: n.label });
  };

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal kg-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="kg-title">
        <div className="notes-header">
          <span id="kg-title"><Icon name="share" size={16} /> Knowledge graph</span>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        <div className="kg-tools">
          <input className="membrowser-search" placeholder="Search chats, memories, documents, projects…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the graph" />
          <div className="membrowser-filters">
            {TYPES.map((t) => {
              const count = (data?.nodes || []).filter((n) => n.type === t.type).length;
              return (
                <button key={t.type} className={`membrowser-filter kg-type-${t.type} ${shown.has(t.type) ? "is-on" : ""}`}
                  onClick={() => setShown((s) => { const n = new Set(s); if (n.has(t.type)) n.delete(t.type); else n.add(t.type); return n.size ? n : s; })}>
                  {t.label} · {count}
                </button>
              );
            })}
            <button className={`membrowser-filter ${connectedOnly ? "is-on" : ""}`} onClick={() => setConnectedOnly((v) => !v)}>Only connected</button>
          </div>
        </div>
        {error ? <p className="cstate-error" style={{ margin: 26 }}>{error}</p> : !data ? <p className="conversation-empty">Loading…</p> : (
          <div className="kg-body">
            <div className="kg-canvas">
              {visible.length === 0 ? <p className="conversation-empty">{data.nodes.length ? "Nothing matches." : "Nothing yet — memories, documents and projects show up here as you use Zenith."}</p> : (
                <>
                  <div className="kg-cols" style={{ width: layout.width }}>
                    {layout.cols.map((c) => <div key={c.type} style={{ width: COL }}>{c.label}</div>)}
                  </div>
                  <svg width={layout.width} height={layout.height} className="graph-svg">
                    {data.edges.map((e, i) => {
                      const a = layout.pos[e.from], b = layout.pos[e.to];
                      if (!a || !b) return null;
                      const on = lit && lit.has(e.from) && lit.has(e.to);
                      // Leave from the right edge of the left-hand column, so lines don't cross labels.
                      const [l, r] = a.x <= b.x ? [a, b] : [b, a];
                      const ax = l.x + COL - 24, bx = r.x + 1, mx = (ax + bx) / 2;
                      return <path key={i} d={`M${ax},${l.y} C${mx},${l.y} ${mx},${r.y} ${bx},${r.y}`} className={`graph-edge ${lit && !on ? "graph-edge-dim" : ""} ${on ? "is-lit" : ""}`} />;
                    })}
                    {visible.map((n) => {
                      const p = layout.pos[n.id];
                      if (!p) return null;
                      const dim = lit && !lit.has(n.id);
                      return (
                        <g key={n.id} transform={`translate(${p.x},${p.y})`} className={`graph-node graph-node-${n.type} ${dim ? "graph-node-dim" : ""} ${sel === n.id ? "is-sel" : ""}`}
                          onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onClick={() => setSel(n.id)} style={{ cursor: "pointer" }}>
                          <circle cx={6} r={sel === n.id ? 6 : 4.5} />
                          <text x={18} y={4}>{n.label.length > 30 ? n.label.slice(0, 29) + "…" : n.label}</text>
                          <title>{n.label}</title>
                        </g>
                      );
                    })}
                  </svg>
                </>
              )}
            </div>
            <aside className="kg-side">
              {!node ? <p className="wf-muted">Pick anything to see what it's linked to.</p> : (
                <>
                  <span className={`mb-badge kg-type-${node.type}`}>{TYPES.find((t) => t.type === node.type)?.one}</span>
                  <h4 className="kg-title">{node.label}</h4>
                  {node.type !== "project" && <button className="wf-btn primary" onClick={() => open(node)}>Open</button>}
                  <h5>{neighbors[node.id].length} connection{neighbors[node.id].length === 1 ? "" : "s"}</h5>
                  <ul className="kg-links">
                    {neighbors[node.id].map((nb, i) => {
                      const other = byId[nb.id];
                      return (
                        <li key={i}><button onClick={() => setSel(nb.id)}>
                          <Icon name={TYPES.find((t) => t.type === other.type)?.icon || "link"} size={13} />
                          <span><em>{nb.dir === "out" ? EDGE_LABEL[nb.kind] : `← ${EDGE_LABEL[nb.kind]}`}</em>{other.label}</span>
                        </button></li>
                      );
                    })}
                  </ul>
                </>
              )}
            </aside>
          </div>
        )}
      </div>
      {preview && <DocumentPreview attachmentId={preview.id} filename={preview.name} onClose={() => setPreview(null)} />}
    </div>,
    document.body,
  );
}
