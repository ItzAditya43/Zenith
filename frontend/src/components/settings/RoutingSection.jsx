import { useEffect, useState } from "react";
import { openModelCompare } from "../../lib/uiEvents.js";
import { recommendedModelForRole, ROLES, ROLE_LABEL } from "./constants.js";
import { api } from "../../lib/api";
import { useSettings } from "./SettingsContext.js";
import Select from "../Select.jsx";

/** Settings → "routing" section. State lives in SettingsPanel (see SettingsContext). */
export default function RoutingSection() {
  const {
    config,
    models,
    hardware,
    routingStatus,
    unavailableModels = {},
    saveError,
    setSaveError,
    overrideSummary,
    refreshModels,
    setOverride,
    setConfig,
  } = useSettings();
  const patch = async (fields) => {
    try {
      setConfig(await api.patchConfig(fields));
      setSaveError?.(null);
    } catch (err) {
      setSaveError?.(`Couldn't save: ${err.message}`);
    }
  };

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
      {saveError && (
        <p className="settings-notice settings-notice-error" role="alert">{saveError}</p>
      )}
      {routingStatus && (
        <p className={`settings-notice ${routingStatus.active ? "settings-notice-ok" : "settings-notice-warn"}`}>
          {routingStatus.active
            ? `Semantic routing is active (using "${routingStatus.embedding_model}" — messages the keyword rules miss can still route correctly).`
            : "Semantic routing is inactive: no model is tagged into the \"embedding\" role, so routing falls back to keyword matching only. Pull an embedding model (e.g. `ollama pull nomic-embed-text`) to enable it."}
        </p>
      )}
      <div className="setting-row">
        <div>
          <strong>Thinking models</strong>
          <span className="setting-hint">
            Models like qwen3.5 and deepseek-r1 can reason before answering. Auto: only on reasoning questions,
            so everyday replies start instantly. The reasoning streams live and can be expanded.
          </span>
        </div>
        <Select
          className="settings-input"
          aria-label="Thinking models"
          value={config?.thinking_mode || "auto"}
          onChange={(e) => patch({ thinking_mode: e.target.value })}
        >
          <option value="auto">Auto</option>
          <option value="on">Always think</option>
          <option value="off">Never think</option>
        </Select>
      </div>
      <RoutingPolicy config={config} patch={patch} />
      <div className="role-grid">
        {ROLES.map((role) => {
          const recommended = recommendedModelForRole(role, models, hardware);
          const current = config?.model_overrides?.[role] || "";
          const dead = current ? unavailableModels[current] : null;
          return (
            <div className="role-card" data-role={role} key={role}>
              <span className="role-card-dot" aria-hidden="true" />
              <span className="role-card-label">{ROLE_LABEL[role]}</span>
              <Select
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
              </Select>
              {dead && (
                <span className="role-card-dead" role="status">
                  Not working: {current} {dead.reason}. Zenith is picking a model automatically for
                  this role until you change it.
                </span>
              )}
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
      <FeedbackTable />
    </section>
  );
}


/** Thumbs and "wrong model" flags from your replies, per model. Read-only
 * on purpose: it informs your pins above, it never changes routing. */
function FeedbackTable() {
  const [data, setData] = useState(null);
  useEffect(() => { api.feedbackSummary().then(setData).catch(() => setData({ models: [], wrong_model_recent: [] })); }, []);
  if (!data) return null;
  return (
    <div style={{ marginTop: "1.5rem" }}>
      <h3 className="settings-section-title">Your feedback</h3>
      <p className="settings-section-desc">
        From the thumbs and “Wrong model?” buttons under replies. Zenith doesn't change routing from this on its own;
        use it to decide what to pin above. <button className="text-btn" onClick={() => openModelCompare()}>Compare models side by side</button>
      </p>
      {data.models.length === 0 ? <p className="setting-hint">No feedback yet.</p> : (
        <table className="fb-table">
          <thead><tr><th>Model</th><th>👍</th><th>👎</th><th>Liked</th><th>Wrong model</th><th>Used as</th></tr></thead>
          <tbody>
            {data.models.map((m) => (
              <tr key={m.model}>
                <td><code>{m.model}</code></td><td>{m.up}</td><td>{m.down}</td>
                <td>{m.approval == null ? "—" : `${Math.round(m.approval * 100)}%`}</td>
                <td className={m.wrong_model ? "warn" : ""}>{m.wrong_model}</td>
                <td>{m.roles.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data.wrong_model_recent.length > 0 && (
        <ul className="fb-recent">
          {data.wrong_model_recent.slice(0, 6).map((r) => (
            <li key={r.message_id}><code>{r.model}</code> picked as {r.route_role || "?"} in “{r.title || "a chat"}”{r.note ? ` — ${r.note}` : ""}</li>
          ))}
        </ul>
      )}
    </div>
  );
}


const POLICIES = [
  ["manual_remote", "This machine, unless I pick otherwise", "Automatic picks run on this machine. You can still choose an Ollama Cloud or API model yourself for a message or a role."],
  ["allow_selected", "Also let it use providers I choose", "Automatic picks may use the remote providers ticked below — they cost money or credits and your message goes to that company."],
  ["local_only", "Only this machine — never send anything out", "Remote models are refused even if picked by hand. Web search still works when you turn it on for a message."],
];

/** Where models may run: the privacy choice for routing, stated up front. */
function RoutingPolicy({ config, patch }) {
  const [provs, setProvs] = useState([]);
  useEffect(() => { api.listProviders().then((r) => setProvs((r.providers || []).filter((p) => !p.local))).catch(() => {}); }, []);
  if (!config) return null;
  const policy = config.routing_policy || (config.route_to_cloud_models ? "allow_selected" : "manual_remote");
  const allowed = new Set(config.routing_allowed_providers?.length ? config.routing_allowed_providers : (config.route_to_cloud_models && !config.routing_policy ? ["*"] : []));
  const toggle = (id) => {
    const next = new Set([...allowed].filter((x) => x !== "*"));
    if (next.has(id)) next.delete(id); else next.add(id);
    patch({ routing_policy: "allow_selected", routing_allowed_providers: [...next] });
  };
  const remotes = [{ id: "ollama-cloud", name: "Ollama Cloud" }, ...provs];
  return (
    <div className="route-policy">
      <strong>Where models may run</strong>
      <div className="route-policy-options" role="radiogroup" aria-label="Where models may run">
        {POLICIES.map(([id, label, hint]) => (
          <label key={id} className={`route-policy-option ${policy === id ? "is-on" : ""}`}>
            <input type="radio" name="routing-policy" checked={policy === id}
              onChange={() => patch({ routing_policy: id, ...(id !== "allow_selected" ? { route_to_cloud_models: false } : {}) })} />
            <span><b>{label}</b><em>{hint}</em></span>
          </label>
        ))}
      </div>
      {policy === "allow_selected" && (
        <div className="route-policy-provs">
          {remotes.map((p) => (
            <label key={p.id}>
              <input type="checkbox" checked={allowed.has("*") || allowed.has(p.id)} onChange={() => toggle(p.id)} /> {p.name}
            </label>
          ))}
          {provs.length === 0 && <span className="setting-hint">Add API providers under Settings → Providers to list them here.</span>}
          <span className="setting-hint">A provider can be limited to certain roles (e.g. only Code) in its own settings.</span>
        </div>
      )}
    </div>
  );
}
