import { api } from "../../lib/api";
import { useSettings } from "./SettingsContext.js";

/** Settings → "council" section. State lives in SettingsPanel (see SettingsContext). */
export default function CouncilSection() {
  const {
    config,
    setConfig,
    models,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Council of models</h3>
      <p className="settings-section-desc">
        Pick 2 or more installed models. When the Council toggle in the composer is on,
        every message goes to all of them at once, in parallel — free, since they're
        already on your machine. Answers show up as branches on the reply; flip
        between them with the ‹ 1/N › switcher.
      </p>
      <div className="role-grid">
        {models.map((m) => {
          const checked = (config?.council_models || []).includes(m.name);
          return (
            <label className="role-card" key={m.name} style={{ cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={checked}
                onChange={async (e) => {
                  const current = config?.council_models || [];
                  const next = e.target.checked
                    ? [...current, m.name]
                    : current.filter((n) => n !== m.name);
                  const updated = await api.patchConfig({ council_models: next });
                  setConfig(updated);
                }}
                style={{ marginRight: "0.5rem" }}
              />
              <span className="role-card-label">{m.name}</span>
            </label>
          );
        })}
        {models.length === 0 && <p className="model-empty">Loading models…</p>}
      </div>
      {(config?.council_models || []).length === 1 && (
        <p className="settings-hint-note">
          Pick at least one more model — Council needs 2+ to be worth running.
        </p>
      )}
    </section>
  );
}
