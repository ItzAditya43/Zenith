import { api } from "../../lib/api";
import { useSettings } from "./SettingsContext.js";

/** Settings → "skills" section. State lives in SettingsPanel (see SettingsContext). */
export default function SkillsSection() {
  const {
    onClose,
    onUseSkill,
    skills,
    skillsError,
    refreshSkills,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Skills</h3>
      <p className="settings-section-desc">
        When agent mode repeats the exact same ordered tool sequence across
        two separate turns, Zenith auto-saves it as a reusable playbook here —
        no manual curation needed. Click "Use" to drop the original prompt back
        into the composer as a starting point.
      </p>
      {skillsError && <p className="settings-error">{skillsError}</p>}
      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {skills.map((s) => (
          <li key={s.id}>
            <span className="model-name" style={{ flex: 1 }}>
              {s.name}
              {s.description && (
                <span style={{ display: "block", fontSize: "0.75em", color: "var(--text-tertiary)" }}>
                  {s.description}
                </span>
              )}
            </span>
            <span className="settings-row" style={{ gap: "0.5rem" }}>
              <button
                className="text-btn"
                onClick={() => {
                  onUseSkill(s.prompt_template);
                  onClose();
                }}
              >
                Use
              </button>
              <button
                className="icon-btn"
                onClick={() => api.deleteSkill(s.id).then(refreshSkills)}
                title="Delete"
                aria-label="Delete skill"
              >
                ×
              </button>
            </span>
          </li>
        ))}
        {skills.length === 0 && !skillsError && (
          <li className="model-empty">
            No skills detected yet — repeat a multi-step agent task twice and one
            will show up here automatically.
          </li>
        )}
      </ul>
    </section>
  );
}
