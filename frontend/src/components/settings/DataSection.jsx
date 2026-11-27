import { useEffect, useState } from "react";
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
            <ImportBatches key={importStatus} />
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

      <TracePrivacy />

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


function ImportBatches() {
  const [batches, setBatches] = useState([]);
  useEffect(() => { api.importBatches().then(setBatches).catch(() => {}); }, []);
  if (!batches.length) return null;
  const undo = async (b) => {
    const { confirmDialog } = await import("../../lib/dialogs.js");
    if (!(await confirmDialog({ title: "Undo this import?", message: `Deletes the ${b.conversations} chat(s) it created, including anything you've added to them since.`, confirmLabel: "Delete them", danger: true }))) return;
    await api.undoImport(b.batch_id);
    setBatches(await api.importBatches());
  };
  return (
    <span style={{ display: "block", marginTop: "0.4rem" }}>
      Recent imports:
      {batches.map((b) => (
        <span key={b.batch_id} style={{ display: "block" }}>
          {new Date(b.imported_at * 1000).toLocaleString()} · {b.source} · {b.conversations} chat(s){" "}
          <button className="text-btn" onClick={() => undo(b)}>Undo</button>
        </span>
      ))}
    </span>
  );
}


function TracePrivacy() {
  const [cfg, setCfg] = useState(null);
  useEffect(() => { api.getConfig().then(setCfg).catch(() => {}); }, []);
  if (!cfg) return null;
  const set = async (patch) => setCfg(await api.patchConfig(patch));
  return (
    <>
      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Keep prompts in turn traces</span>
          <span className="setting-hint">
            Traces record which model answered, what was retrieved and how long it took. Your prompt text is
            left out unless this is on. Traces older than {cfg.trace_retention_days || 30} days are deleted.
          </span>
        </div>
        <button className={`switch ${cfg.trace_store_prompts ? "switch-on" : ""}`} role="switch" aria-checked={!!cfg.trace_store_prompts}
          onClick={() => set({ trace_store_prompts: !cfg.trace_store_prompts })}>
          <span className="switch-thumb" />
        </button>
      </div>
      <div className="setting-row">
        <div className="setting-meta"><span className="setting-label">Keep traces for</span></div>
        <input type="number" className="settings-input" style={{ flex: "0 0 90px" }} min={1} max={365}
          aria-label="Days to keep traces" defaultValue={cfg.trace_retention_days || 30}
          onBlur={(e) => set({ trace_retention_days: Math.max(1, Math.min(365, Number(e.target.value) || 30)) })} />
      </div>
    </>
  );
}
