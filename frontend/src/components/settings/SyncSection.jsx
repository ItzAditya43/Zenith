import { useSettings } from "./SettingsContext.js";

/** Settings → "sync" section. State lives in SettingsPanel (see SettingsContext). */
export default function SyncSection() {
  const {
    syncPassphrase,
    setSyncPassphrase,
    pairCode,
    pairExpiresIn,
    joinHost,
    setJoinHost,
    joinCode,
    setJoinCode,
    syncStatus,
    syncBusy,
    importBlobText,
    setImportBlobText,
    startPairing,
    joinWithCode,
    exportSnapshot,
    importSnapshot,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Sync</h3>
      <p className="settings-section-desc">
        Multi-device sync is deliberately two-factor: a passphrase you choose
        <em> and</em> a sync secret that only ever moves between devices through a
        short-lived, single-use pairing code — never sent in plaintext, never stored
        anywhere but on your devices. Knowing the passphrase alone doesn't decrypt
        anything on an unpaired device. This syncs Notes, To-dos, Calendar, Personas,
        Projects, and Memories — not full chat history.
      </p>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        1. Pair a new device
      </h3>
      <p className="settings-section-desc">
        On the device you already trust, generate a code. On the new device, enter
        that code plus this trusted device's address (both must be reachable on the
        same network — LAN or Tailscale).
      </p>
      <div className="settings-row">
        <button className="settings-btn-primary" onClick={startPairing}>
          Generate pairing code
        </button>
        {pairCode && (
          <span className="setting-hint">
            Code: <strong>{pairCode}</strong> (valid {pairExpiresIn}s — enter this on the
            new device)
          </span>
        )}
      </div>

      <div className="settings-row" style={{ marginTop: "0.75rem" }}>
        <input
          className="settings-input"
          placeholder="Trusted device address, e.g. http://192.168.1.20:8420"
          aria-label="Trusted device address"
          value={joinHost}
          onChange={(e) => setJoinHost(e.target.value)}
        />
        <input
          className="settings-input"
          placeholder="Pairing code"
          aria-label="Pairing code"
          value={joinCode}
          onChange={(e) => setJoinCode(e.target.value)}
        />
        <button className="settings-btn-primary" onClick={joinWithCode} disabled={syncBusy}>
          {syncBusy ? "…" : "Join"}
        </button>
      </div>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        2. Sync a snapshot
      </h3>
      <p className="settings-section-desc">
        Once paired, export an encrypted snapshot on one device and import it on the
        other. Manual and on-demand — not continuous background sync.
      </p>
      <div className="settings-row">
        <input
          className="settings-input"
          type="password"
          placeholder="Sync passphrase (same on both devices)"
          aria-label="Sync passphrase"
          value={syncPassphrase}
          onChange={(e) => setSyncPassphrase(e.target.value)}
        />
      </div>
      <div className="settings-row" style={{ marginTop: "0.5rem" }}>
        <button className="settings-btn-primary" onClick={exportSnapshot} disabled={syncBusy}>
          Export snapshot
        </button>
      </div>
      <div className="settings-row" style={{ marginTop: "0.5rem" }}>
        <textarea
          className="settings-input"
          style={{ width: "100%", minHeight: "70px" }}
          placeholder="Paste an exported snapshot's contents here to import…"
          aria-label="Snapshot to import"
          value={importBlobText}
          onChange={(e) => setImportBlobText(e.target.value)}
        />
      </div>
      <div className="settings-row" style={{ marginTop: "0.5rem" }}>
        <button className="settings-btn-primary" onClick={importSnapshot} disabled={syncBusy}>
          Import snapshot
        </button>
      </div>
      {syncStatus && (
        <p className={syncStatus.ok ? "setting-hint" : "settings-error"} style={{ marginTop: "0.5rem" }}>
          {syncStatus.message}
        </p>
      )}
    </section>
  );
}
