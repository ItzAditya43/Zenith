import { useState } from "react";
import { api } from "../../lib/api";
import { useSettings } from "./SettingsContext.js";
import { pickNativeDirectory } from "../../lib/directoryPicker";
import Icon from "../Icon.jsx";

/** Settings → "folders" section. State lives in SettingsPanel (see SettingsContext). */
export default function FoldersSection() {
  const {
    folders,
    foldersError,
    newFolderPath,
    setNewFolderPath,
    scanningFolder,
    addFolder,
    removeFolder,
    toggleFolder,
    scanFolderNow,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Watched folders</h3>
      <p className="settings-section-desc">
        Point Zenith at a folder and it periodically re-indexes matching files
        (.md/.txt/.py/.js/.ts/.json) so their content is recalled in chat automatically
        — no manual upload per file. Paths are resolved on the <em>backend</em>, which
        in the Docker deployment means the container's own filesystem unless you've
        added a host bind mount in docker-compose.yml.
      </p>

      <div className="settings-row">
        <input
          className="settings-input"
          placeholder="/path/to/notes"
          aria-label="Folder path to watch"
          value={newFolderPath}
          onChange={(e) => setNewFolderPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addFolder()}
        />
        <button
          type="button"
          className="settings-btn workdir-browse-btn"
          onClick={async () => {
            const selected = await pickNativeDirectory({
              defaultPath: newFolderPath || undefined,
              title: "Select Folder to Watch",
            });
            if (selected) setNewFolderPath(selected);
          }}
          title="Browse folder"
        >
          <Icon name="folder-open" size={14} /> Browse…
        </button>
        <button className="settings-btn-primary" onClick={addFolder}>
          Watch
        </button>
      </div>
      {foldersError && <p className="settings-error">{foldersError}</p>}

      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {folders.map((f) => (
          <li key={f.id} style={{ opacity: f.enabled ? 1 : 0.5, flexWrap: "wrap" }}>
            <span className="model-name" style={{ flex: 1 }}>
              {f.path}
              <span className="setting-hint" style={{ display: "block" }}>
                {f.last_scanned_at
                  ? `Last scanned ${new Date(f.last_scanned_at * 1000).toLocaleString()}`
                  : "Not scanned yet"}
              </span>
            </span>
            <span className="settings-row" style={{ gap: "0.5rem" }}>
              <button
                className="text-btn"
                onClick={() => scanFolderNow(f.id)}
                disabled={scanningFolder === f.id}
              >
                {scanningFolder === f.id ? "Scanning…" : "Scan now"}
              </button>
              <button className="text-btn" onClick={() => toggleFolder(f.id, !f.enabled)} title={f.enabled ? "Pause watching" : "Resume watching"}>
                {f.enabled ? "Watching" : "Paused"}
              </button>
              <button className="icon-btn" onClick={() => removeFolder(f.id)} title="Stop watching" aria-label="Stop watching folder">
                ×
              </button>
            </span>
            <FolderFilters folder={f} />
          </li>
        ))}
        {folders.length === 0 && !foldersError && (
          <li className="model-empty">No folders watched yet.</li>
        )}
      </ul>
    </section>
  );
}


/** Which files in a watched folder get indexed: extensions, include and
 * exclude globs, and a preview of the result before scanning. */
function FolderFilters({ folder }) {
  const [open, setOpen] = useState(false);
  const [exts, setExts] = useState(folder.extensions || "");
  const [inc, setInc] = useState(folder.include_patterns || "");
  const [exc, setExc] = useState(folder.exclude_patterns || "");
  const [prev, setPrev] = useState(null);
  const [msg, setMsg] = useState("");
  const save = async () => {
    setMsg("");
    try {
      await api.setFolderPatterns(folder.id, inc, exc, exts);
      setPrev(await api.previewFolder(folder.id));
      setMsg("Saved. The next scan applies it; files that no longer match are removed from the index.");
    } catch (e) {
      setMsg(e.message);
    }
  };
  if (!open) {
    return (
      <button className="text-btn folder-filters-toggle" onClick={async () => { setOpen(true); setPrev(await api.previewFolder(folder.id).catch(() => null)); }}>
        Filters{folder.include_patterns || folder.exclude_patterns ? " (custom)" : ""}
      </button>
    );
  }
  return (
    <div className="folder-filters">
      <label>File types <input className="settings-input" value={exts} onChange={(e) => setExts(e.target.value)} placeholder=".md,.txt" /></label>
      <label>Only include <input className="settings-input" value={inc} onChange={(e) => setInc(e.target.value)} placeholder="e.g. notes/**, *.md (empty = everything)" /></label>
      <label>Skip <input className="settings-input" value={exc} onChange={(e) => setExc(e.target.value)} placeholder="e.g. drafts/**, *secret*, archive" /></label>
      <div className="settings-row">
        <button className="settings-btn-primary" onClick={save}>Save &amp; preview</button>
        <button className="text-btn" onClick={() => setOpen(false)}>Close</button>
      </div>
      {msg && <span className="setting-hint">{msg}</span>}
      {prev && (
        <div className="setting-hint" role="status">
          {prev.counts.index} file{prev.counts.index === 1 ? "" : "s"} will be indexed
          {prev.counts.excluded ? ` · ${prev.counts.excluded} skipped by your patterns` : ""}
          {prev.counts.not_included ? ` · ${prev.counts.not_included} not in "Only include"` : ""}
          {prev.counts.outside ? ` · ${prev.counts.outside} symlink(s) pointing outside this folder are never followed` : ""}
          {prev.files.length > 0 && <pre className="diag-preview">{prev.files.join("\n")}{prev.counts.index > prev.files.length ? "\n…" : ""}</pre>}
        </div>
      )}
    </div>
  );
}
