import Icon from "./Icon.jsx";

// Chip style matched to the existing secondary-button visual weight
// (see .settings-btn-secondary / .theme-choice-btn) since this codebase
// has no dedicated .kbd / key-chip class to reuse.
const kbdStyle = {
  display: "inline-block",
  padding: "1px 7px",
  borderRadius: "var(--radius-sm, 4px)",
  border: "1px solid var(--border-color, #444)",
  background: "var(--bg-secondary, rgba(127,127,127,0.12))",
  fontFamily: "inherit",
  fontSize: "0.8em",
  lineHeight: "1.6",
};

function Kbd({ children }) {
  return <kbd style={kbdStyle}>{children}</kbd>;
}

// Every entry here was verified against a real keydown handler in
// App.jsx (the global `window.addEventListener("keydown", ...)` effect
// and its command-palette `hint` fields) or Composer.jsx's own
// `onKeyDown`/`onKeyUp` handlers — nothing here is invented.
const GROUPS = [
  {
    title: "General",
    shortcuts: [
      { keys: ["⌘/Ctrl", "K"], desc: "Open the command palette" },
      { keys: ["⌘/Ctrl", "."], desc: "Toggle focus mode" },
      { keys: ["?"], desc: "Open this shortcuts reference" },
      { keys: ["Esc"], desc: "Close this overlay, the command palette, exit focus mode, or close settings/search (in that order)" },
    ],
  },
  {
    title: "Chat",
    shortcuts: [
      { keys: ["Enter"], desc: "Send the message" },
      { keys: ["Shift", "Enter"], desc: "Insert a newline without sending" },
      { keys: ["Space"], desc: "Hold to talk (push-to-talk voice input) when the composer area is focused but the text box isn't" },
    ],
  },
];

/** Reference overlay listing every real keyboard shortcut in the app.
 * Mirrors HealthPanel's overlay/dialog structure and CSS classes exactly. */
export default function ShortcutsOverlay({ onClose }) {
  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div
        className="calendar-modal"
        style={{ width: "min(480px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-overlay-title"
      >
        <div className="calendar-header">
          <span id="shortcuts-overlay-title">Keyboard shortcuts</span>
          <div style={{ display: "flex", gap: "var(--space-1)" }}>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
        <div style={{ padding: "var(--space-3) var(--space-4)", maxHeight: "75vh", overflowY: "auto" }}>
          {GROUPS.map((group) => (
            <div key={group.title} style={{ marginBottom: "var(--space-3)" }}>
              <div className="health-overall" style={{ marginBottom: "var(--space-2)" }}>
                <span>{group.title}</span>
              </div>
              <div className="health-list">
                {group.shortcuts.map((s) => (
                  <div className="health-row" key={s.desc}>
                    <div className="health-row-main">
                      <span style={{ display: "flex", gap: "4px" }}>
                        {s.keys.map((k, i) => (
                          <Kbd key={i}>{k}</Kbd>
                        ))}
                      </span>
                    </div>
                    <div className="health-row-detail">
                      <span className="health-row-field">{s.desc}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
