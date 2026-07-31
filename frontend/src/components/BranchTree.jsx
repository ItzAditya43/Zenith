import { useState } from "react";
import Icon from "./Icon.jsx";

function preview(text) {
  if (!text) return "(empty)";
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > 56 ? clean.slice(0, 56) + "…" : clean;
}

/**
 * The parent/child branching model already tracks every alternate version
 * of every message — this just surfaces it as a clickable tree instead of
 * hiding it behind a "‹ 2/3 ›" arrow. One row per branch point, one chip
 * per version; the active chip is highlighted.
 */
export default function BranchTree({ branches, messages, onSwitchBranch, onClose }) {
  const points = Object.entries(branches || {}).filter(([, sibs]) => sibs.length > 1);
  const [hovered, setHovered] = useState(null);

  if (points.length === 0) {
    return (
      <div className="branch-tree-panel">
        <div className="branch-tree-header">
          <span>Branches</span>
          <button className="icon-btn" onClick={onClose} title="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div className="branch-tree-empty">No alternate branches in this conversation yet.</div>
      </div>
    );
  }

  const orderIndex = new Map(messages.map((m, i) => [m.id, i]));
  points.sort((a, b) => {
    const ai = orderIndex.get(a[1][0]?.id) ?? 0;
    const bi = orderIndex.get(b[1][0]?.id) ?? 0;
    return ai - bi;
  });

  return (
    <div className="branch-tree-panel">
      <div className="branch-tree-header">
        <span>Branches</span>
        <button className="icon-btn" onClick={onClose} title="Close">
          <Icon name="x" size={14} />
        </button>
      </div>
      <div className="branch-tree-list">
        {points.map(([parentKey, sibs]) => (
          <div className="branch-tree-point" key={parentKey}>
            <div className="branch-tree-stem" />
            <div className="branch-tree-versions">
              {sibs.map((s, idx) => (
                <button
                  key={s.id}
                  className={`branch-tree-chip ${s.active ? "is-active" : ""} ${hovered === s.id ? "is-hovered" : ""}`}
                  onMouseEnter={() => setHovered(s.id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => onSwitchBranch(s.id)}
                  title={s.content}
                >
                  <span className="branch-tree-chip-idx">v{idx + 1}</span>
                  <span className="branch-tree-chip-text">{preview(s.content)}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
