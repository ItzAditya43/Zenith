import { useSettings } from "./SettingsContext.js";

/** Settings → "accessibility" section. State lives in SettingsPanel (see SettingsContext). */
export default function AccessibilitySection() {
  const {
    fontScale,
    onFontScaleChange,
    highContrast,
    onHighContrastChange,
    reduceMotion,
    onReduceMotionChange,
    dyslexiaFont,
    onDyslexiaFontChange,
    underlineLinks,
    onUnderlineLinksChange,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Accessibility</h3>
      <p className="settings-section-desc">
        These apply everywhere in Zenith, on top of whichever theme you've picked, and
        are remembered on this device.
      </p>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Text size</span>
          <span className="setting-hint">Scales all text in the app, not just chat messages.</span>
        </div>
        <div className="theme-choice">
          {[
            { id: "0.875", label: "Small" },
            { id: "1", label: "Default" },
            { id: "1.15", label: "Large" },
            { id: "1.35", label: "X-Large" },
          ].map((o) => (
            <button
              key={o.id}
              className={`theme-choice-btn ${fontScale === o.id ? "is-selected" : ""}`}
              onClick={() => onFontScaleChange(o.id)}
              aria-pressed={fontScale === o.id}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">High contrast</span>
          <span className="setting-hint">
            Stronger text/background separation and bolder borders, for low-vision or
            bright-environment use.
          </span>
        </div>
        <button
          className={`switch ${highContrast ? "switch-on" : ""}`}
          onClick={() => onHighContrastChange(!highContrast)}
          role="switch"
          aria-checked={!!highContrast}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Reduce motion</span>
          <span className="setting-hint">
            Turns off transitions, ambient backgrounds, and animated UI regardless of
            your OS setting.
          </span>
        </div>
        <button
          className={`switch ${reduceMotion ? "switch-on" : ""}`}
          onClick={() => onReduceMotionChange(!reduceMotion)}
          role="switch"
          aria-checked={!!reduceMotion}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Dyslexia-friendly font</span>
          <span className="setting-hint">
            Switches body text to a font with wider letter spacing and looser line height.
          </span>
        </div>
        <button
          className={`switch ${dyslexiaFont ? "switch-on" : ""}`}
          onClick={() => onDyslexiaFontChange(!dyslexiaFont)}
          role="switch"
          aria-checked={!!dyslexiaFont}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Always underline links</span>
          <span className="setting-hint">
            Helps distinguish links from regular text without relying on color alone.
          </span>
        </div>
        <button
          className={`switch ${underlineLinks ? "switch-on" : ""}`}
          onClick={() => onUnderlineLinksChange(!underlineLinks)}
          role="switch"
          aria-checked={!!underlineLinks}
        >
          <span className="switch-thumb" />
        </button>
      </div>
    </section>
  );
}
