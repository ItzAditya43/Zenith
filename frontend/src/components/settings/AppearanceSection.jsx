import { ANIMATIONS, THEME_ANIMATIONS } from "../../lib/ambientAnimations";
import { THEMES } from "./constants.js";
import { useSettings } from "./SettingsContext.js";

/** Settings → "appearance" section. State lives in SettingsPanel (see SettingsContext). */
export default function AppearanceSection() {
  const {
    theme,
    onThemeChange,
    voiceReplyEnabled,
    onVoiceReplyChange,
    density,
    onDensityChange,
    ambientAnim,
    onAmbientChange,
    notificationsEnabled,
    onNotificationsChange,
    config,
    toggleNtfyEnabled,
    saveNtfyConfig,
    toggleWakeWordEnabled,
    saveWakeWordPhrase,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Appearance</h3>
      <p className="settings-section-desc">
        Zenith adapts to your environment. Switch themes any time — your choice is
        remembered on this device.
      </p>

      <div className="setting-row setting-row-stack">
        <div className="setting-meta">
          <span className="setting-label">Theme</span>
          <span className="setting-hint">
            Eight full re-skins — colors, fonts, shapes, shadows — not just a
            light/dark toggle.
          </span>
        </div>
        <div className="theme-grid">
          {THEMES.map((t) => (
            <button
              key={t.id}
              className={`theme-card ${theme === t.id ? "is-selected" : ""}`}
              onClick={() => onThemeChange(t.id)}
              aria-pressed={theme === t.id}
              style={{ background: t.bg, color: t.fg, fontFamily: t.font }}
            >
              <span className="theme-card-swatches">
                <span style={{ background: t.accent }} />
              </span>
              <span className="theme-card-label">{t.name}</span>
            </button>
          ))}
        </div>
      </div>

      {THEME_ANIMATIONS[theme]?.length > 0 && (
        <div className="setting-row">
          <div className="setting-meta">
            <span className="setting-label">Ambient background</span>
            <span className="setting-hint">
              A subtle animated layer behind the chat. Off by default; only shown
              for animations that fit this theme.
            </span>
          </div>
          <select
            className="settings-input"
            value={ambientAnim}
            onChange={(e) => onAmbientChange(e.target.value)}
            aria-label="Ambient background"
          >
            <option value="none">None</option>
            {ANIMATIONS.filter((a) => THEME_ANIMATIONS[theme].includes(a.id)).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Speak replies aloud</span>
          <span className="setting-hint">
            When on, Zenith reads assistant responses using your chosen voice engine.
          </span>
        </div>
        <button
          className={`switch ${voiceReplyEnabled ? "switch-on" : ""}`}
          onClick={() => onVoiceReplyChange(!voiceReplyEnabled)}
          role="switch"
          aria-checked={voiceReplyEnabled}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Message density</span>
          <span className="setting-hint">
            Compact fits more on screen — tighter spacing, smaller type.
          </span>
        </div>
        <div className="theme-choice">
          {["comfortable", "compact"].map((d) => (
            <button
              key={d}
              className={`theme-choice-btn ${density === d ? "is-selected" : ""}`}
              onClick={() => onDensityChange(d)}
              aria-pressed={density === d}
            >
              <span className="theme-choice-label">
                {d === "comfortable" ? "Comfortable" : "Compact"}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Desktop notifications</span>
          <span className="setting-hint">
            Get a system notification when a response finishes while this tab is in the
            background, or when a scheduled task runs. Asks the browser for permission.
          </span>
        </div>
        <button
          className={`switch ${notificationsEnabled ? "switch-on" : ""}`}
          onClick={() => onNotificationsChange(!notificationsEnabled)}
          role="switch"
          aria-checked={!!notificationsEnabled}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Push notifications (ntfy)</span>
          <span className="setting-hint">
            Get schedule/digest/urgent-email alerts on your phone via{" "}
            <a href="https://ntfy.sh" target="_blank" rel="noreferrer">ntfy.sh</a> (or your
            own self-hosted instance) even while Zenith isn't open. Off by default — this is
            a deliberate exception to "nothing leaves your machine": once on, a short
            notification text is sent to the ntfy server you configure below.
          </span>
        </div>
        <button
          className={`switch ${config?.notify_ntfy_enabled ? "switch-on" : ""}`}
          onClick={() => toggleNtfyEnabled(!config?.notify_ntfy_enabled)}
          role="switch"
          aria-checked={!!config?.notify_ntfy_enabled}
        >
          <span className="switch-thumb" />
        </button>
      </div>
      {config?.notify_ntfy_enabled && (
        <div className="setting-row setting-row-stack">
          <input
            className="settings-input"
            placeholder="ntfy server URL (default https://ntfy.sh)"
            defaultValue={config?.notify_ntfy_url || ""}
            aria-label="ntfy server URL"
            onBlur={(e) => saveNtfyConfig({ notify_ntfy_url: e.target.value.trim() || "https://ntfy.sh" })}
          />
          <input
            className="settings-input"
            placeholder="Topic (a private, hard-to-guess name — anyone who knows it can read your notifications)"
            defaultValue={config?.notify_ntfy_topic || ""}
            aria-label="ntfy topic"
            onBlur={(e) => saveNtfyConfig({ notify_ntfy_topic: e.target.value.trim() })}
          />
          <div className="setting-hint">
            Events that push a notification:
            {["digest_generated", "schedule_completed", "urgent_email", "memory_conflict_found", "folder_file_added"].map((ev) => {
              const active = (config?.notify_event_types || []).includes(ev);
              return (
                <button
                  key={ev}
                  className={`theme-choice-btn ${active ? "is-selected" : ""}`}
                  style={{ marginLeft: "0.4rem", marginTop: "0.4rem" }}
                  onClick={() => {
                    const current = config?.notify_event_types || [];
                    const next = active ? current.filter((e) => e !== ev) : [...current, ev];
                    saveNtfyConfig({ notify_event_types: next });
                  }}
                >
                  {ev.replace(/_/g, " ")}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Wake word</span>
          <span className="setting-hint">
            Say a phrase to start talking hands-free, instead of holding the mic button.
            Off by default — turning this on means Zenith listens to the microphone
            continuously in the background (short local voice-activity bursts only, nothing
            is stored beyond the normal transcribe call). A "listening" badge shows
            whenever this is actually on.
          </span>
        </div>
        <button
          className={`switch ${config?.wake_word_enabled ? "switch-on" : ""}`}
          onClick={() => toggleWakeWordEnabled(!config?.wake_word_enabled)}
          role="switch"
          aria-checked={!!config?.wake_word_enabled}
        >
          <span className="switch-thumb" />
        </button>
      </div>
      {config?.wake_word_enabled && (
        <div className="setting-row">
          <div className="setting-meta">
            <span className="setting-label">Wake phrase</span>
          </div>
          <input
            className="settings-input"
            defaultValue={config?.wake_word_phrase || "hey zenith"}
            aria-label="Wake phrase"
            onBlur={(e) => saveWakeWordPhrase(e.target.value.trim() || "hey zenith")}
          />
        </div>
      )}
    </section>
  );
}
