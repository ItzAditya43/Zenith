import { useState } from "react";
import { api } from "../../lib/api";
import { useSettings } from "./SettingsContext.js";
import ApiKeys from "./ApiKeys.jsx";
import PasscodeSettings from "./PasscodeSettings.jsx";

/** Settings → "data" section. State lives in SettingsPanel (see SettingsContext). */
export default function DataSection() {
  const {
    importing,
    importStatus,
    lockEnabled,
    setLockEnabled,
    handleImport,
  } = useSettings();
  const [mdMeta, setMdMeta] = useState(true);
  const [mdAtt, setMdAtt] = useState(true);

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
        <a className="settings-btn-primary" href={`${api.exportUrl("markdown")}?metadata=${mdMeta}&attachments=${mdAtt}`} download>
          Download .zip
        </a>
      </div>
      <div className="settings-row" style={{ gap: "1.25rem", margin: "-0.25rem 0 0.75rem", fontSize: "var(--text-xs)" }}>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={mdMeta} onChange={(e) => setMdMeta(e.target.checked)} /> Models, times and tags
        </label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={mdAtt} onChange={(e) => setMdAtt(e.target.checked)} /> Attachment names
        </label>
      </div>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Import
      </h3>
      <p className="settings-section-desc">
        Bring your history over from another tool, or move it between two Zenith
        instances — upload a ChatGPT or Claude <code>conversations.json</code>, an Open WebUI
        chat export, an OpenAI-style message list (LM Studio, LibreChat, scripts), a Markdown
        transcript (Zenith's own export, or <code>## User</code> / <code>**You:**</code> style), or a
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
            {importStatus || "Original messages and timestamps are kept, each chat is tagged with where it came from, and chats you already imported are skipped."}
          </span>
        </div>
        <label className="settings-btn-primary" style={{ cursor: "pointer" }}>
          {importing ? "Importing…" : "Choose a file"}
          <input
            type="file"
            accept="application/json,.json,.md,.markdown,.txt,text/markdown,text/plain"
            hidden
            disabled={importing}
            onChange={handleImport}
          />
        </label>
      </div>

      <ApiKeys />

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Passcode lock
      </h3>
      <p className="settings-section-desc">
        Require a passcode to open Zenith on this machine — useful if others use the same
        computer or reach it over the network. It is a login gate, <strong>not</strong> encryption:
        the database, attachments and settings on disk stay readable by anyone with access to
        this computer's files, and they can also remove the lock.
      </p>
      <PasscodeSettings lockEnabled={lockEnabled} setLockEnabled={setLockEnabled} />
    </section>
  );
}
