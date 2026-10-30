import { api } from "../../lib/api";
import { useSettings } from "./SettingsContext.js";

/** Settings → "data" section. State lives in SettingsPanel (see SettingsContext). */
export default function DataSection() {
  const {
    importing,
    importStatus,
    lockEnabled,
    lockInput,
    setLockInput,
    lockMsg,
    handleSetPasscode,
    handleDisablePasscode,
    handleImport,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Data</h3>
      <p className="settings-section-desc">
        Everything Zenith knows about you, in a format you can actually read and keep
        — no lock-in. Downloads run locally against your own backend.
      </p>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Export as JSON</span>
          <span className="setting-hint">
            Complete, machine-readable — every conversation, message, memory, persona,
            project, quick action, and watched folder. (Schedules aren't included —
            they're re-created per-instance from Settings -&gt; Schedules.)
          </span>
        </div>
        <a className="settings-btn-primary" href={api.exportUrl("json")} download>
          Download .json
        </a>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Export as Markdown</span>
          <span className="setting-hint">
            One readable .md file per conversation, zipped — good for archiving or
            reading outside Zenith.
          </span>
        </div>
        <a className="settings-btn-primary" href={api.exportUrl("markdown")} download>
          Download .zip
        </a>
      </div>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Import
      </h3>
      <p className="settings-section-desc">
        Bring your history over from another tool, or move it between two Zenith
        instances — upload a ChatGPT/Claude <code>conversations.json</code>, or a
        <code> zenith-export.json</code> downloaded from "Export as JSON" above (on this
        machine or another one). A Zenith-to-Zenith import also re-creates projects
        (conversations are re-linked to the new project), quick actions, and watched
        folders (skipped if the path doesn't exist on this machine). Zenith detects
        which kind of file it is automatically.
      </p>
      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Import a file</span>
          <span className="setting-hint">
            {importStatus || "Your original messages and timestamps are preserved."}
          </span>
        </div>
        <label className="settings-btn-primary" style={{ cursor: "pointer" }}>
          {importing ? "Importing…" : "Choose a file"}
          <input
            type="file"
            accept="application/json,.json"
            hidden
            disabled={importing}
            onChange={handleImport}
          />
        </label>
      </div>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Passcode lock
      </h3>
      <p className="settings-section-desc">
        Require a passcode to open Zenith on this machine — useful if others use the same
        computer. Note: this is a login gate, <strong>not</strong> at-rest encryption; the
        database file itself is still readable by anyone with filesystem access.
      </p>
      <div className="settings-row">
        <input
          className="settings-input"
          type="password"
          placeholder={lockEnabled ? "Current passcode (to change/disable)" : "Set a passcode (min 4 chars)"}
          aria-label={lockEnabled ? "Current passcode" : "Set a passcode"}
          value={lockInput}
          onChange={(e) => setLockInput(e.target.value)}
        />
        <button className="settings-btn-primary" onClick={handleSetPasscode}>
          {lockEnabled ? "Change" : "Enable lock"}
        </button>
        {lockEnabled && (
          <button className="settings-btn-secondary" onClick={handleDisablePasscode}>
            Disable
          </button>
        )}
      </div>
      {lockMsg && <span className="setting-hint">{lockMsg}</span>}
    </section>
  );
}
