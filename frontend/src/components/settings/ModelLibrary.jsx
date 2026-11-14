import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import Icon from "../Icon.jsx";

const CATEGORIES = [
  { key: "", label: "All" },
  { key: "tools", label: "Tools / agents" },
  { key: "vision", label: "Vision" },
  { key: "thinking", label: "Thinking" },
  { key: "embedding", label: "Embedding" },
  { key: "cloud", label: "Cloud" },
];

function formatPulls(n) {
  if (n == null) return null;
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}K`;
  return String(n);
}

/** How a download of `gb` will run on this machine. */
function fitFor(gb, hardware) {
  if (gb == null || !hardware) return null;
  const vram = hardware.hardware?.gpu?.vram_gb || 0;
  const ram = hardware.hardware?.ram_gb || 0;
  if (vram && gb <= vram * 0.9) return { level: "comfortable", text: "fits your GPU" };
  if (ram && gb <= (vram + ram) * 0.7) return { level: "tight", text: vram ? "partly on CPU, slower" : "runs on CPU" };
  return { level: "will_struggle", text: "too big for this machine" };
}

/** Signed-in Ollama account and plan: decides which cloud models work. */
export function OllamaAccount() {
  const [acct, setAcct] = useState(null);
  useEffect(() => {
    api.ollamaAccount().then(setAcct).catch(() => setAcct({ reachable: false }));
  }, []);
  if (!acct) return null;
  if (!acct.reachable) {
    return <p className="settings-notice settings-notice-warn">Can't reach Ollama to check your account.</p>;
  }
  if (acct.signed_in) {
    const paid = acct.plan && acct.plan !== "free";
    return (
      <div className="account-card">
        <span className="account-avatar" aria-hidden="true">{(acct.name || "?")[0].toUpperCase()}</span>
        <div className="account-meta">
          <strong>Signed in to Ollama as {acct.name}</strong>
          <span className="setting-hint">
            {paid
              ? `${acct.plan[0].toUpperCase()}${acct.plan.slice(1)} plan: cloud models run on Ollama's servers under your subscription.`
              : "Free plan: some cloud models need credits or a subscription. Zenith checks a cloud model before using it and skips it if your plan doesn't cover it."}
          </span>
        </div>
        {!paid && (
          <a className="settings-btn-secondary account-upgrade" href="https://ollama.com/pricing" target="_blank" rel="noreferrer">
            See plans
          </a>
        )}
      </div>
    );
  }
  return (
    <div className="account-card">
      <span className="account-avatar" aria-hidden="true"><Icon name="cloud" size={15} /></span>
      <div className="account-meta">
        <strong>Not signed in to Ollama</strong>
        <span className="setting-hint">
          Local models work without an account. To use cloud models, sign in
          {acct.signin_url ? "" : " by running "}{!acct.signin_url && <code>ollama signin</code>}{acct.signin_url ? " with the button" : " in a terminal"}.
        </span>
      </div>
      {acct.signin_url && (
        <a className="settings-btn-primary" href={acct.signin_url} target="_blank" rel="noreferrer">Sign in</a>
      )}
    </div>
  );
}

/** Search the Ollama library and download a size of any model. */
export default function ModelLibrary({ hardware, installed, onPull, pullBusy }) {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [category, setCategory] = useState("");
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null); // model name whose sizes are shown
  const [tags, setTags] = useState({}); // name -> tags | {error}

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(() => {
      setError(null);
      api.modelLibrary(submitted, category)
        .then((r) => { if (!cancelled) setResults(r.models); })
        .catch((err) => { if (!cancelled) { setResults([]); setError(err.message); } });
    }, 0);
    return () => { cancelled = true; clearTimeout(t); };
  }, [submitted, category]);

  // Search as you type, after a short pause.
  useEffect(() => {
    const t = setTimeout(() => setSubmitted(query.trim()), 350);
    return () => clearTimeout(t);
  }, [query]);

  const toggle = (name) => {
    if (open === name) { setOpen(null); return; }
    setOpen(name);
    if (!tags[name]) {
      api.modelLibraryTags(name)
        .then((r) => setTags((t) => ({ ...t, [name]: r.tags })))
        .catch((err) => setTags((t) => ({ ...t, [name]: { error: err.message } })));
    }
  };

  const isInstalled = (tag) => installed.some((m) => m === tag || m === `${tag}:latest` || (tag.endsWith(":latest") && m === tag.slice(0, -7)));

  return (
    <div className="lib">
      <div className="lib-search">
        <Icon name="search" size={14} />
        <input
          placeholder="Search the Ollama library, e.g. qwen, coder, vision…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search the Ollama library"
        />
      </div>
      <div className="lib-cats" role="group" aria-label="Filter by capability">
        {CATEGORIES.map((c) => (
          <button key={c.key} type="button" className={`lib-cat ${category === c.key ? "is-active" : ""}`} aria-pressed={category === c.key} onClick={() => setCategory(c.key)}>
            {c.label}
          </button>
        ))}
      </div>
      {error && <p className="settings-notice settings-notice-error" role="alert">{error}</p>}
      {results == null && <p className="setting-hint">Loading the library…</p>}
      {results?.length === 0 && !error && <p className="setting-hint">No models found.</p>}
      <ul className="lib-list">
        {results?.map((m) => (
          <li key={m.name} className={`lib-item ${open === m.name ? "is-open" : ""}`}>
            <button className="lib-item-head" onClick={() => toggle(m.name)} aria-expanded={open === m.name}>
              <span className="lib-item-main">
                <span className="lib-item-name">
                  {m.name}
                  {m.cloud && <span className="lib-chip lib-chip-cloud">cloud</span>}
                </span>
                {m.description && <span className="lib-item-desc">{m.description}</span>}
                <span className="lib-item-meta">
                  {m.capabilities.filter((c) => c !== "cloud").map((c) => <span key={c} className="lib-chip">{c}</span>)}
                  {m.sizes.length > 0 && <span className="lib-sizes">{m.sizes.join(" · ")}</span>}
                  {m.pulls != null && <span className="lib-pulls"><Icon name="download" size={11} /> {formatPulls(m.pulls)}</span>}
                </span>
              </span>
              <Icon name={open === m.name ? "chevron-up" : "chevron-down"} size={14} />
            </button>
            {open === m.name && (
              <div className="lib-tags">
                {!tags[m.name] && <p className="setting-hint">Loading sizes…</p>}
                {tags[m.name]?.error && <p className="setting-hint">{tags[m.name].error}</p>}
                {Array.isArray(tags[m.name]) && tags[m.name].length === 0 && <p className="setting-hint">No sizes listed.</p>}
                {Array.isArray(tags[m.name]) && tags[m.name].map((t) => {
                  const fit = t.cloud || m.cloud ? { level: "cloud", text: "runs on Ollama's servers" } : fitFor(t.size_gb, hardware);
                  const have = isInstalled(t.tag);
                  return (
                    <div className="lib-tag" key={t.tag}>
                      <span className="lib-tag-name">{t.tag}</span>
                      <span className="lib-tag-size">{t.size || ""}{t.context ? ` · ${t.context} context` : ""}</span>
                      {fit && <span className={`fit-chip fit-chip-${fit.level}`}>{fit.text}</span>}
                      <button
                        className={have ? "settings-btn-secondary" : "settings-btn-primary"}
                        disabled={have || pullBusy}
                        onClick={() => onPull(t.tag)}
                      >
                        {have ? "Installed" : t.cloud || m.cloud ? "Add" : "Download"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
