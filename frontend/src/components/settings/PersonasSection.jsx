import { useSettings } from "./SettingsContext.js";

/** Settings → "personas" section. State lives in SettingsPanel (see SettingsContext). */
export default function PersonasSection() {
  const {
    personas,
    newPersonaName,
    setNewPersonaName,
    newPersonaIcon,
    setNewPersonaIcon,
    newPersonaPrompt,
    setNewPersonaPrompt,
    personasError,
    addPersona,
    deletePersona,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Personas</h3>
      <p className="settings-section-desc">
        Named system-prompt presets you can switch per conversation from the chat
        header — a persona overrides the global system prompt for that conversation
        only. Conversations without one keep using the global prompt.
      </p>

      <div className="setting-row setting-row-stack">
        <div className="settings-row">
          <input
            className="settings-input"
            style={{ flex: "0 0 60px" }}
            placeholder="Icon"
            aria-label="Persona icon"
            value={newPersonaIcon}
            onChange={(e) => setNewPersonaIcon(e.target.value)}
            maxLength={4}
          />
          <input
            className="settings-input"
            placeholder="Name, e.g. Coding buddy"
            aria-label="Persona name"
            value={newPersonaName}
            onChange={(e) => setNewPersonaName(e.target.value)}
          />
        </div>
        <textarea
          className="settings-textarea"
          rows={3}
          placeholder="System prompt for this persona…"
          aria-label="Persona system prompt"
          value={newPersonaPrompt}
          onChange={(e) => setNewPersonaPrompt(e.target.value)}
        />
        <div className="settings-row">
          <button className="settings-btn-primary" onClick={addPersona}>
            Add persona
          </button>
        </div>
      </div>
      {personasError && <p className="settings-error">{personasError}</p>}

      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {personas.map((p) => (
          <li key={p.id}>
            <span className="model-name" style={{ flex: 1 }}>
              {p.icon ? `${p.icon} ` : ""}
              {p.name}
            </span>
            <button className="icon-btn" onClick={() => deletePersona(p.id)} title="Delete" aria-label={`Delete persona ${p.name}`}>
              ×
            </button>
          </li>
        ))}
        {personas.length === 0 && !personasError && (
          <li className="model-empty">No personas yet — add one above.</li>
        )}
      </ul>
    </section>
  );
}
