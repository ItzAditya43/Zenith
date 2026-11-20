import { useEffect, useState } from "react";
import { api } from "../../lib/api";

const METHODS = [
  ["hyprland", "Window control", "open, focus and move apps"],
  ["keyboard", "Keyboard", "type and press shortcuts"],
  ["accessibility", "Click by name", "buttons and fields from the accessibility tree"],
  ["ocr", "Click by text", "words read off the screen"],
  ["screenshot", "See the screen", "described by your vision model"],
];

/** Settings → Agent tools → Desktop control. */
export default function DesktopControl({ config, setConfig }) {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.desktopStatus().then(setSt).catch(() => setSt(null));
  }, []);

  const toggle = async () => {
    setConfig(await api.patchConfig({ desktop_control_enabled: !config?.desktop_control_enabled }));
  };
  const setA11y = async (on) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.setDesktopAccessibility(on);
      setSt((s) => ({ ...s, accessibility_on: r.accessibility_on }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>Desktop control</h3>
      <p className="settings-section-desc">
        Let the agent act on your desktop: open apps and links, switch windows, type, press shortcuts
        and click buttons by name. Open it from anywhere with <kbd className="keycap">Super</kbd>+<kbd className="keycap">Space</kbd>{" "}
        (Hyprland). Looking at the screen runs freely; every action asks you first unless autonomy is
        full-auto. It never types into or clicks in a password manager.
      </p>
      <div className="setting-row">
        <div>
          <strong>Allow desktop control</strong>
          <span className="setting-hint">Off by default. The agent runs as you, so it can reach anything you can.</span>
        </div>
        <button
          className={`switch ${config?.desktop_control_enabled ? "switch-on" : ""}`}
          onClick={toggle}
          disabled={!config?.agent_enabled}
          role="switch"
          aria-checked={!!config?.desktop_control_enabled}
          aria-label="Allow desktop control"
        >
          <span className="switch-thumb" />
        </button>
      </div>
      {st && (
        <div className="dc-methods">
          {METHODS.map(([key, label, hint]) => (
            <span key={key} className={`dc-method ${st[key] ? "is-on" : ""}`} title={hint}>
              <span className="dc-dot" aria-hidden="true" /> {label}
              <span className="sr-only">{st[key] ? "available" : "not available"}</span>
            </span>
          ))}
        </div>
      )}
      {st && st.accessibility_on !== null && (
        <div className="setting-row">
          <div>
            <strong>App accessibility</strong>
            <span className="setting-hint">
              Makes apps list their buttons and fields so the agent can press them by name instead of
              reading pixels — the same setting screen readers use. Applies to apps opened after you
              turn it on. Chrome and Electron apps may also need <code>--force-renderer-accessibility</code>.
            </span>
          </div>
          <button
            className={`switch ${st.accessibility_on ? "switch-on" : ""}`}
            onClick={() => setA11y(!st.accessibility_on)}
            disabled={busy}
            role="switch"
            aria-checked={!!st.accessibility_on}
            aria-label="App accessibility"
          >
            <span className="switch-thumb" />
          </button>
        </div>
      )}
      {error && <p className="settings-notice settings-notice-error" role="alert">{error}</p>}
    </>
  );
}
