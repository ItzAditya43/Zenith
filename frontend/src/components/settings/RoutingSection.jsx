import { recommendedModelForRole, ROLES, ROLE_LABEL } from "./constants.js";
import { useSettings } from "./SettingsContext.js";

/** Settings → "routing" section. State lives in SettingsPanel (see SettingsContext). */
export default function RoutingSection() {
  const {
    config,
    models,
    hardware,
    routingStatus,
    overrideSummary,
    refreshModels,
    setOverride,
  } = useSettings();

  return (
    <section className="settings-section">
      <div className="settings-row settings-row-space-between">
        <div>
          <h3 className="settings-section-title">Model routing</h3>
          <p className="settings-section-desc settings-section-desc-inline">
            Zenith auto-picks a model per capability. Override any role to pin it.
          </p>
        </div>
        <button className="text-btn" onClick={refreshModels}>
          Refresh
        </button>
      </div>
      {routingStatus && (
        <p className={`settings-notice ${routingStatus.active ? "settings-notice-ok" : "settings-notice-warn"}`}>
          {routingStatus.active
            ? `Semantic routing is active (using "${routingStatus.embedding_model}" — messages the keyword rules miss can still route correctly).`
            : "Semantic routing is inactive: no model is tagged into the \"embedding\" role, so routing falls back to keyword matching only. Pull an embedding model (e.g. `ollama pull nomic-embed-text`) to enable it."}
        </p>
      )}
      <div className="role-grid">
        {ROLES.map((role) => {
          const recommended = recommendedModelForRole(role, models, hardware);
          const current = config?.model_overrides?.[role] || "";
          return (
            <div className="role-card" data-role={role} key={role}>
              <span className="role-card-dot" aria-hidden="true" />
              <span className="role-card-label">{ROLE_LABEL[role]}</span>
              <select
                className="role-card-select"
                value={current}
                onChange={(e) => setOverride(role, e.target.value)}
                data-role={role}
                aria-label={`Model for ${ROLE_LABEL[role]}`}
              >
                <option value="">Auto-detect</option>
                {models.map((m) => (
                  <option value={m.name} key={m.name}>
                    {m.name} {m.roles?.length ? `(${m.roles.join(", ")})` : ""}
                  </option>
                ))}
              </select>
              {recommended && recommended.name !== current && (
                <button
                  className="text-btn role-card-recommend"
                  onClick={() => setOverride(role, recommended.name)}
                  title={`${recommended.name} — ${recommended.fit === "comfortable" ? "fits your GPU/RAM comfortably" : "the best fit available among your installed models"}`}
                >
                  Use recommended: {recommended.name} ({recommended.fit.replace("_", " ")})
                </button>
              )}
            </div>
          );
        })}
      </div>

      {overrideSummary.length > 0 && (
        <div className="settings-subsection" style={{ marginTop: "1.5rem" }}>
          <h4 className="settings-section-title" style={{ fontSize: "0.95rem" }}>
            Learned from your corrections
          </h4>
          <p className="settings-section-desc settings-section-desc-inline">
            Whenever you manually pick a different model than the one auto-routing chose,
            Zenith remembers it. These are patterns from the last 30 days — pin one to stop
            the router guessing wrong for that kind of message.
          </p>
          <ul className="role-grid" style={{ listStyle: "none", padding: 0 }}>
            {overrideSummary.map((o) => (
              <li className="role-card" key={`${o.auto_role}-${o.auto_model}-${o.override_model}`}>
                <span className="role-card-dot" aria-hidden="true" />
                <span className="role-card-label">
                  {ROLE_LABEL[o.auto_role] || o.auto_role}
                </span>
                <span className="settings-section-desc-inline">
                  You've sent {ROLE_LABEL[o.auto_role]?.toLowerCase() || o.auto_role}-flagged
                  messages to <code>{o.override_model}</code> instead of the auto-picked{" "}
                  <code>{o.auto_model}</code> — {o.count} time{o.count === 1 ? "" : "s"}.
                </span>
                <button
                  className="text-btn role-card-recommend"
                  onClick={() => setOverride(o.auto_role, o.override_model)}
                  title={`Pin ${o.override_model} to the "${o.auto_role}" role`}
                >
                  Pin this
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
