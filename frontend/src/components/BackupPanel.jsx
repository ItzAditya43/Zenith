import { useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

/** Full backup/restore overlay.
 *
 * Unlike Settings -> Data's JSON/Markdown export (your data, readable),
 * this downloads the actual on-disk state — the SQLite database,
 * config.json, and every attachment file — via GET /api/backup/create,
 * and can restore it via POST /api/backup/restore. Restore is
 * destructive (overwrites the live database) so it's gated behind an
 * explicit confirmation checkbox before the button even enables. */
export default function BackupPanel({ onClose }) {
  const [file, setFile] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);
  const [checking, setChecking] = useState(false);

  const canRestore = !!file && confirmed && !busy && preview?.ok;

  const pick = async (f) => {
    setFile(f);
    setResult(null);
    setError(null);
    setPreview(null);
    if (!f) return;
    setChecking(true);
    try {
      setPreview(await api.inspectBackup(f));
    } catch (err) {
      setError(err.message || "Couldn't read that backup.");
    } finally {
      setChecking(false);
    }
  };

  const handleRestore = async () => {
    if (!canRestore) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.restoreBackup(file, true);
      setResult(res);
    } catch (err) {
      setError(err.message || "Restore failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div
        className="calendar-modal"
        style={{ width: "min(520px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="backup-panel-title"
      >
        <div className="calendar-header">
          <span id="backup-panel-title">Backup &amp; restore</span>
          <div style={{ display: "flex", gap: "var(--space-1)" }}>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>

        <div style={{ padding: "var(--space-3) var(--space-4)", maxHeight: "75vh", overflowY: "auto" }}>
          <h3 className="settings-section-title">Download backup</h3>
          <p className="settings-section-desc">
            One zip with everything: the SQLite database, <code>config.json</code>, and every
            uploaded attachment file. Keep this somewhere safe before a version upgrade or any
            risky change — this is what you'd restore from if something goes wrong.
          </p>
          <div className="setting-row">
            <div className="setting-meta">
              <span className="setting-label">Full backup</span>
              <span className="setting-hint">Database + config + attachments, as one .zip</span>
            </div>
            <a className="settings-btn-primary" href={api.backupUrl()} download>
              Download backup
            </a>
          </div>

          <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
            Restore from backup
          </h3>
          <p className="settings-section-desc" style={{ color: "var(--color-danger, #d33)" }}>
            <strong>Warning:</strong> restoring <strong>overwrites your current database, config,
            and attachments</strong> with the contents of the backup zip. Your current state is
            copied to a safety folder first, but anything created since that backup was taken will
            still be lost from the live app. A <strong>backend restart is required</strong> after
            restoring for the restored data to actually take effect.
          </p>

          <div className="setting-row" style={{ flexDirection: "column", alignItems: "stretch", gap: "var(--space-2)" }}>
            <input
              type="file"
              accept=".zip"
              aria-label="Backup file to restore"
              onChange={(e) => pick(e.target.files?.[0] || null)}
            />

            {checking && <p className="settings-section-desc">Checking the backup…</p>}
            {preview && (
              <div className={`backup-preview ${preview.ok ? "" : "is-bad"}`} role="status">
                <strong>{preview.ok ? "Backup looks good" : "This backup can't be restored"}</strong>
                <ul>
                  {preview.created_at && <li>Taken {new Date(preview.created_at * 1000).toLocaleString()}</li>}
                  {preview.app_version && <li>Zenith {preview.app_version} · schema {preview.schema_version ?? "?"} (this install: {preview.current_schema_version ?? "?"})</li>}
                  <li>
                    {Object.entries(preview.counts || {}).map(([k, v]) => `${v} ${k}`).join(" · ") || "No readable tables"}
                  </li>
                  <li>{preview.attachments} attachment file{preview.attachments === 1 ? "" : "s"}{preview.includes_config ? " · settings included" : " · no settings file"}</li>
                  {preview.notes?.map((n) => <li key={n}>{n}</li>)}
                  {preview.problems?.map((p) => <li key={p} className="backup-problem">{p}</li>)}
                </ul>
              </div>
            )}

            <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>
                I understand this overwrites my current data and requires a restart afterward.
              </span>
            </label>

            <button
              className="settings-btn-primary"
              onClick={handleRestore}
              disabled={!canRestore}
            >
              {busy ? "Restoring…" : "Restore from backup"}
            </button>
          </div>

          {error && <p className="conversation-empty">{error}</p>}
          {result && (
            <p className="conversation-empty">
              Restored. Your previous state was saved to{" "}
              <code>{result.pre_restore_snapshot}</code>. Restart the backend now for the restored
              data to take effect.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
