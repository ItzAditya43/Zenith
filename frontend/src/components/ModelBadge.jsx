import { useState } from "react";

const ROLE_LABEL = {
  general: "General",
  small_fast: "Quick",
  vision: "Vision",
  code: "Code",
  reasoning: "Reasoning",
};

export default function ModelBadge({ model, role, reason, confidence, matchedOn }) {
  const [open, setOpen] = useState(false);
  if (!model) return null;
  return (
    <div className="model-badge" data-role={role}>
      <span className="model-badge-dot" aria-hidden="true">◆</span>
      <span className="model-badge-role">{(ROLE_LABEL[role] || role || "").toLowerCase()}</span>
      <span className="model-badge-sep" aria-hidden="true">·</span>
      <span className="model-badge-name">{model}</span>
      {typeof confidence === "number" && (
        <span className="model-badge-meter" title={`Routing confidence ${(confidence * 100).toFixed(0)}%`}>
          <span aria-hidden="true">
            {"▰".repeat(Math.round(confidence * 5))}
            <span className="model-badge-meter-empty">{"▱".repeat(5 - Math.round(confidence * 5))}</span>
          </span>{" "}
          {confidence.toFixed(2)}
        </span>
      )}
      <button
        className="model-badge-info"
        onClick={() => setOpen((v) => !v)}
        title="Why this model?"
        aria-label="Routing explanation"
      >
        ?
      </button>
      {open && (
        <div className="model-badge-popover">
          <p className="model-badge-popover-reason">{reason || "Routed by capability."}</p>
          {confidence !== undefined && (
            <p className="model-badge-popover-row">
              Confidence: <strong>{(confidence * 100).toFixed(0)}%</strong>
            </p>
          )}
          {matchedOn && (
            <p className="model-badge-popover-row">
              Matched: <code>{matchedOn}</code>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
