import { useEffect, useState } from "react";
import { api } from "../lib/api";

const ROLES = ["general", "code", "vision", "reasoning", "small_fast", "embedding"];
const ROLE_LABEL = {
  general: "General chat",
  code: "Code",
  vision: "Vision (images/video)",
  reasoning: "Reasoning / math",
  small_fast: "Quick / small talk",
  embedding: "Embeddings",
};

const SECTIONS = [
  { id: "appearance", label: "Appearance", icon: "◐" },
  { id: "connection", label: "Connection", icon: "⚡" },
  { id: "routing", label: "Model routing", icon: "⇄" },
  { id: "models", label: "Installed models", icon: "▦" },
  { id: "voice", label: "Voice & audio", icon: "🎙" },
];

export default function SettingsPanel({ onClose, theme, onThemeChange, voiceReplyEnabled, onVoiceReplyChange }) {
  const [config, setConfig] = useState(null);
  const [models, setModels] = useState([]);
  const [modelsError, setModelsError] = useState(null);
  const [host, setHost] = useState("");
  const [saving, setSaving] = useState(false);
  const [activeSection, setActiveSection] = useState("appearance");

  const refreshModels = () => {
    api
      .listModels()
      .then((m) => {
        setModels(m);
        setModelsError(null);
      })
      .catch((err) => setModelsError(err.message));
  };

  useEffect(() => {
    api.getConfig().then((c) => {
      setConfig(c);
      setHost(c.ollama_host);
    });
    refreshModels();
  }, []);

  const saveHost = async () => {
    setSaving(true);
    const updated = await api.patchConfig({ ollama_host: host });
    setConfig(updated);
    setSaving(false);
    refreshModels();
  };

  const setOverride = async (role, modelName) => {
    const updated = await api.patchConfig({
      model_overrides: { ...config.model_overrides, [role]: modelName || null },
    });
    setConfig(updated);
    refreshModels();
  };

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div
        className="settings-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Settings"
      >
        <div className="settings-header">
          <div className="settings-title">
            <span className="settings-title-mark" aria-hidden="true" />
            <div>
              <h2>Settings</h2>
              <p className="settings-subtitle">Tune how Cortex runs on your machine</p>
            </div>
          </div>
          <button className="icon-btn settings-close" onClick={onClose} title="Close (Esc)">
            ×
          </button>
        </div>

        <div className="settings-body">
          <nav className="settings-nav" aria-label="Settings sections">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                className={`settings-nav-item ${activeSection === s.id ? "is-active" : ""}`}
                onClick={() => setActiveSection(s.id)}
              >
                <span className="settings-nav-icon" aria-hidden="true">
                  {s.icon}
                </span>
                {s.label}
              </button>
            ))}
          </nav>

          <div className="settings-content">
            {activeSection === "appearance" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Appearance</h3>
                <p className="settings-section-desc">
                  Cortex adapts to your environment. Switch themes any time — your choice is
                  remembered on this device.
                </p>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Theme</span>
                    <span className="setting-hint">Dark is easiest on the eyes at night.</span>
                  </div>
                  <div className="theme-choice">
                    {["dark", "light"].map((t) => (
                      <button
                        key={t}
                        className={`theme-choice-btn ${theme === t ? "is-selected" : ""}`}
                        onClick={() => onThemeChange(t)}
                        aria-pressed={theme === t}
                      >
                        <span className={`theme-swatch theme-swatch-${t}`} aria-hidden="true" />
                        <span className="theme-choice-label">
                          {t === "dark" ? "Dark" : "Light"}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Speak replies aloud</span>
                    <span className="setting-hint">
                      When on, Cortex reads assistant responses using your chosen voice engine.
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
              </section>
            )}

            {activeSection === "connection" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Ollama connection</h3>
                <p className="settings-section-desc">
                  Cortex talks to a local Ollama instance. Point it at the host it's running on.
                </p>
                <div className="setting-row setting-row-stack">
                  <label className="setting-label" htmlFor="ollama-host">
                    Ollama host
                  </label>
                  <div className="settings-row">
                    <input
                      id="ollama-host"
                      className="settings-input"
                      value={host}
                      onChange={(e) => setHost(e.target.value)}
                      placeholder="http://localhost:11434"
                    />
                    <button className="settings-btn-primary" onClick={saveHost} disabled={saving}>
                      {saving ? "Saving…" : "Save"}
                    </button>
                  </div>
                  {modelsError && (
                    <p className="settings-error">
                      {modelsError} — check the host above and that Ollama is running.
                    </p>
                  )}
                </div>
              </section>
            )}

            {activeSection === "routing" && (
              <section className="settings-section">
                <div className="settings-row settings-row-space-between">
                  <div>
                    <h3 className="settings-section-title">Model routing</h3>
                    <p className="settings-section-desc settings-section-desc-inline">
                      Cortex auto-picks a model per capability. Override any role to pin it.
                    </p>
                  </div>
                  <button className="text-btn" onClick={refreshModels}>
                    Refresh
                  </button>
                </div>
                <div className="role-grid">
                  {ROLES.map((role) => (
                    <div className="role-card" data-role={role} key={role}>
                      <span className="role-card-dot" aria-hidden="true" />
                      <span className="role-card-label">{ROLE_LABEL[role]}</span>
                      <select
                        className="role-card-select"
                        value={config?.model_overrides?.[role] || ""}
                        onChange={(e) => setOverride(role, e.target.value)}
                        data-role={role}
                      >
                        <option value="">Auto-detect</option>
                        {models.map((m) => (
                          <option value={m.name} key={m.name}>
                            {m.name} {m.roles?.length ? `(${m.roles.join(", ")})` : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {activeSection === "models" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Installed models</h3>
                <p className="settings-section-desc">
                  Everything below is running locally on your Ollama. No data leaves your machine.
                </p>
                <ul className="model-list">
                  {models.map((m) => (
                    <li key={m.name}>
                      <span className="model-name">{m.name}</span>
                      <span className="model-roles">
                        {m.roles?.map((r) => (
                          <span key={r} className="role-chip" data-role={r}>
                            {r}
                          </span>
                        ))}
                      </span>
                    </li>
                  ))}
                  {models.length === 0 && !modelsError && <li className="model-empty">Loading…</li>}
                </ul>
              </section>
            )}

            {activeSection === "voice" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Voice & audio</h3>
                <p className="settings-section-desc">
                  Configure speech-to-text and text-to-speech. Hold the mic in the composer to
                  dictate a message.
                </p>

                <div className="setting-row setting-row-stack">
                  <label className="setting-label" htmlFor="whisper-size">
                    Whisper model size
                  </label>
                  <select
                    id="whisper-size"
                    className="settings-select"
                    value={config?.whisper_model_size}
                    onChange={async (e) => {
                      const updated = await api.patchConfig({ whisper_model_size: e.target.value });
                      setConfig(updated);
                    }}
                  >
                    {["tiny", "base", "small", "medium", "large-v3"].map((s) => (
                      <option value={s} key={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="setting-row setting-row-stack">
                  <label className="setting-label" htmlFor="tts-engine">
                    TTS engine
                  </label>
                  <select
                    id="tts-engine"
                    className="settings-select"
                    value={config?.tts_engine}
                    onChange={async (e) => {
                      const updated = await api.patchConfig({ tts_engine: e.target.value });
                      setConfig(updated);
                    }}
                  >
                    <option value="piper">Piper (offline, neural)</option>
                    <option value="pyttsx3">System voice (fallback)</option>
                  </select>
                </div>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}