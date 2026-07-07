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

export default function SettingsPanel({ onClose }) {
  const [config, setConfig] = useState(null);
  const [models, setModels] = useState([]);
  const [modelsError, setModelsError] = useState(null);
  const [host, setHost] = useState("");
  const [saving, setSaving] = useState(false);

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

  if (!config) return null;

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
      <div className="settings-panel" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>Settings</h2>
          <button className="icon-btn" onClick={onClose}>
            ×
          </button>
        </div>

        <section className="settings-section">
          <h3>Ollama connection</h3>
          <div className="settings-row">
            <input
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
        </section>

        <section className="settings-section">
          <div className="settings-row settings-row-space-between">
            <h3>Model routing</h3>
            <button className="text-btn" onClick={refreshModels}>
              Refresh
            </button>
          </div>
          <p className="settings-hint">
            Cortex auto-picks a model per capability from what's installed. Override any
            role below to pin it to a specific model.
          </p>
          {ROLES.map((role) => (
            <div className="settings-row settings-role-row" key={role}>
              <label>{ROLE_LABEL[role]}</label>
              <select
                value={config.model_overrides?.[role] || ""}
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
        </section>

        <section className="settings-section">
          <h3>Installed models</h3>
          <ul className="model-list">
            {models.map((m) => (
              <li key={m.name}>
                <span>{m.name}</span>
                <span className="model-roles">
                  {m.roles?.map((r) => (
                    <span key={r} className="role-chip" data-role={r}>
                      {r}
                    </span>
                  ))}
                </span>
              </li>
            ))}
            {models.length === 0 && !modelsError && <li>Loading…</li>}
          </ul>
        </section>

        <section className="settings-section">
          <h3>Voice</h3>
          <div className="settings-row settings-role-row">
            <label>Whisper model size</label>
            <select
              value={config.whisper_model_size}
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
          <div className="settings-row settings-role-row">
            <label>TTS engine</label>
            <select
              value={config.tts_engine}
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
      </div>
    </div>
  );
}
