import { useEffect, useState } from "react";
import { api } from "../lib/api";

// provider id -> runs on this machine/network? Filled once per page load.
let localProviders = null;
let loading = null;
function useLocalProviders() {
  const [map, setMap] = useState(localProviders);
  useEffect(() => {
    if (localProviders) return;
    loading = loading || api.listProviders().then((r) => {
      localProviders = Object.fromEntries((r.providers || []).map((p) => [p.id, !!p.local]));
      return localProviders;
    }).catch(() => ({}));
    loading.then(setMap);
  }, []);
  return map || {};
}

const ROLE_LABEL = {
  general: "General",
  small_fast: "Quick",
  vision: "Vision",
  code: "Code",
  reasoning: "Reasoning",
};

function where(model, locals) {
  if (model.includes("::")) {
    const prov = model.split("::")[0];
    return { label: `via ${prov}`, remote: !locals[prov] };
  }
  const tag = model.includes(":") ? model.split(":").pop().toLowerCase() : "";
  if (tag === "cloud" || tag.endsWith("-cloud")) return { label: "Ollama Cloud", remote: true };
  return { label: "this machine", remote: false };
}

export default function ModelBadge({ model, role, reason, confidence, matchedOn }) {
  const [open, setOpen] = useState(false);
  const locals = useLocalProviders();
  if (!model) return null;
  const w = where(model, locals);
  return (
    <div className="model-badge" data-role={role}>
      <span className="model-badge-dot" aria-hidden="true">◆</span>
      <span className="model-badge-role">{(ROLE_LABEL[role] || role || "").toLowerCase()}</span>
      <span className="model-badge-sep" aria-hidden="true">·</span>
      <span className="model-badge-name">{model.includes("::") ? model.split("::")[1] : model}</span>
      <span className={`model-badge-where ${w.remote ? "is-remote" : ""}`} title={w.remote ? "Ran on another company's servers" : "Ran on this machine (or your own server)"}>
        {w.label}
      </span>
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
