import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import { useEscapeToClose } from "../hooks/useEscapeToClose";

const COLUMNS = [
  { type: "project", label: "Projects" },
  { type: "conversation", label: "Conversations" },
  { type: "memory", label: "Memories" },
  { type: "document", label: "Documents" },
];

const ROW_HEIGHT = 30;
const COL_WIDTH = 260;
const PADDING_TOP = 40;

/** A grouped-column layout (not a physics-based force graph — that's a
 * lot of moving parts for what's fundamentally a "what connects to
 * what" question) with SVG lines for edges. Honest about what data
 * exists: only real foreign-key relationships already in the schema,
 * nothing inferred. */
export default function KnowledgeGraphPanel({ onClose, onOpenConversation }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);
  const containerRef = useRef(null);
  useEscapeToClose(onClose);

  useEffect(() => {
    api.getKnowledgeGraph().then(setData).catch((err) => setError(err.message));
  }, []);

  const layout = useMemo(() => {
    if (!data) return null;
    const byType = {};
    for (const col of COLUMNS) byType[col.type] = [];
    for (const n of data.nodes) {
      if (byType[n.type]) byType[n.type].push(n);
    }
    const positions = {};
    COLUMNS.forEach((col, colIdx) => {
      byType[col.type].forEach((n, rowIdx) => {
        positions[n.id] = {
          x: colIdx * COL_WIDTH + COL_WIDTH / 2,
          y: PADDING_TOP + rowIdx * ROW_HEIGHT,
          node: n,
        };
      });
    });
    const height = Math.max(
      400,
      PADDING_TOP + Math.max(...COLUMNS.map((c) => byType[c.type].length), 1) * ROW_HEIGHT + 40
    );
    return { byType, positions, width: COLUMNS.length * COL_WIDTH, height };
  }, [data]);

  if (error) {
    return (
      <div className="notes-overlay" onClick={onClose}>
        <div className="notes-modal" onClick={(e) => e.stopPropagation()}>
          <div className="notes-header">
            <span>Knowledge graph</span>
            <button className="icon-btn" onClick={onClose}><Icon name="x" size={14} /></button>
          </div>
          <p className="settings-error">{error}</p>
        </div>
      </div>
    );
  }

  const connectedIds = (id) => {
    if (!data) return new Set();
    const s = new Set([id]);
    for (const e of data.edges) {
      if (e.from === id) s.add(e.to);
      if (e.to === id) s.add(e.from);
    }
    return s;
  };
  const highlighted = hoveredId ? connectedIds(hoveredId) : null;

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div
        className="notes-modal graph-modal"
        style={{ width: "min(1100px, calc(100vw - 3rem))", height: "min(720px, calc(100vh - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Knowledge graph"
      >
        <div className="notes-header">
          <span>Knowledge graph — what's connected to what</span>
          <button className="icon-btn" onClick={onClose} title="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        {!layout ? (
          <div className="code-editor-empty">Loading…</div>
        ) : layout.width === 0 || data.nodes.length === 0 ? (
          <div className="code-editor-empty">Nothing to show yet — memories, documents, and projects will appear here as you use them.</div>
        ) : (
          <div className="graph-scroll" ref={containerRef}>
            <div className="graph-columns">
              {COLUMNS.map((col) => (
                <div className="graph-column-label" key={col.type} style={{ width: COL_WIDTH }}>
                  {col.label} ({layout.byType[col.type].length})
                </div>
              ))}
            </div>
            <svg width={layout.width} height={layout.height} className="graph-svg">
              {data.edges.map((e, i) => {
                const a = layout.positions[e.from];
                const b = layout.positions[e.to];
                if (!a || !b) return null;
                const dim = highlighted && !(highlighted.has(e.from) && highlighted.has(e.to));
                return (
                  <line
                    key={i}
                    x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                    className={`graph-edge ${dim ? "graph-edge-dim" : ""}`}
                  />
                );
              })}
              {Object.values(layout.positions).map(({ x, y, node }) => {
                const dim = highlighted && !highlighted.has(node.id);
                return (
                  <g
                    key={node.id}
                    transform={`translate(${x},${y})`}
                    className={`graph-node graph-node-${node.type} ${dim ? "graph-node-dim" : ""}`}
                    onMouseEnter={() => setHoveredId(node.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    onClick={() => {
                      if (node.type === "conversation" && onOpenConversation) {
                        onOpenConversation(node.id.replace("conversation:", ""));
                        onClose();
                      }
                    }}
                    style={{ cursor: node.type === "conversation" ? "pointer" : "default" }}
                  >
                    <circle r={4} />
                    <text x={10} y={4}>{node.label}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}
