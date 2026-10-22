import { api } from "../../lib/api";
import { useSettings } from "./SettingsContext.js";

/** Settings → "voice" section. State lives in SettingsPanel (see SettingsContext). */
export default function VoiceSection() {
  const {
    config,
    setConfig,
  } = useSettings();

  return (
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
  );
}
