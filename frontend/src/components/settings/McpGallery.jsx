import { useState } from "react";
import { api } from "../../lib/api";
import { POPULAR_MCP_SERVERS } from "./constants.js";

const CURATED = POPULAR_MCP_SERVERS.map((s) => ({
  ...s,
  args: s.args.split(/\s+/).filter(Boolean),
  env: [],
  curated: true,
}));

// Placeholder args (e.g. /path/to/allow) or required keys mean the user has
// to finish the config, so those fill the form instead of installing.
const needsSetup = (s) => s.env.some((e) => e.required) || s.args.some((a) => a.includes("/path/to"));

/** Settings → Agent → MCP gallery: curated servers plus live search of the
 * official MCP registry. One click installs; anything that needs a key or
 * path is handed to the form below to finish. */
export default function McpGallery({ installed, onInstalled, onPrefill }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState(null);
  const have = new Set(installed.map((s) => s.name));

  const search = async (e) => {
    e.preventDefault();
    if (!query.trim()) return setResults(null);
    setBusy("search");
    setNote(null);
    try {
      setResults(await api.searchMcpRegistry(query.trim()));
    } catch (err) {
      setNote(err.message);
    } finally {
      setBusy(null);
    }
  };

  const install = async (s) => {
    if (needsSetup(s)) {
      onPrefill(s.name, s.command, s.args.join(" "));
      const keys = s.env.filter((e) => e.required).map((e) => e.name);
      setNote(`${s.name}: finish the form below${keys.length ? ` — needs ${keys.join(", ")}` : " — set the path"}.`);
      return;
    }
    setBusy(s.name);
    setNote(null);
    try {
      const added = await api.addMcpServer(s.name, s.command, s.args);
      onInstalled();
      const tools = await api.getMcpServerTools(added.id).catch(() => null);
      setNote(tools?.length ? `${s.name}: installed, ${tools.length} tools ready.` : `${s.name}: installed — first start may take a minute while ${s.command} downloads it.`);
    } catch (err) {
      setNote(err.message);
    } finally {
      setBusy(null);
    }
  };

  const list = results ?? CURATED;
  return (
    <div className="mcp-gallery">
      <form className="settings-row" onSubmit={search}>
        <input
          className="settings-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the MCP registry — github, notion, postgres…"
          aria-label="Search MCP servers"
        />
        <button className="settings-btn" disabled={busy === "search"}>{busy === "search" ? "Searching…" : "Search"}</button>
      </form>
      {note && <p className="setting-hint" role="status">{note}</p>}
      <ul className="mcp-gallery-list">
        {list.map((s) => (
          <li key={s.full_name || s.name} className="mcp-card">
            <div className="mcp-card-head">
              <strong>{s.name}</strong>
              <span className={`fit-chip ${s.curated ? "fit-chip-comfortable" : "fit-chip-tight"}`}>{s.curated ? "curated" : "community"}</span>
            </div>
            <p className="mcp-card-desc">{s.description}</p>
            <code className="mcp-card-cmd">{s.command} {s.args.join(" ")}</code>
            <div className="mcp-card-foot">
              {s.repository && <a href={s.repository} target="_blank" rel="noreferrer">source</a>}
              <button
                className="settings-btn"
                disabled={have.has(s.name) || busy === s.name}
                onClick={() => install(s)}
              >
                {have.has(s.name) ? "Installed" : busy === s.name ? "Installing…" : needsSetup(s) ? "Set up" : "Install"}
              </button>
            </div>
          </li>
        ))}
        {results?.length === 0 && <li className="model-empty">No locally runnable servers matched.</li>}
      </ul>
    </div>
  );
}
