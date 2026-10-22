import { useSettings } from "./SettingsContext.js";

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
        <button className="settings-btn-primary" onClick={addFolder}>
          Watch
        </button>
      </div>
      {foldersError && <p className="settings-error">{foldersError}</p>}

      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {folders.map((f) => (
          <li key={f.id} style={{ opacity: f.enabled ? 1 : 0.5 }}>
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
              <button className="text-btn" onClick={() => toggleFolder(f.id, !f.enabled)}>
                {f.enabled ? "On" : "Off"}
              </button>
              <button className="icon-btn" onClick={() => removeFolder(f.id)} title="Stop watching" aria-label="Stop watching folder">
                ×
              </button>
            </span>
          </li>
        ))}
        {folders.length === 0 && !foldersError && (
          <li className="model-empty">No folders watched yet.</li>
        )}
      </ul>
    </section>
  );
}
