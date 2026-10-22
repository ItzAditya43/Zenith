import { useSettings } from "./SettingsContext.js";

/** Settings → "automation" section. State lives in SettingsPanel (see SettingsContext). */
export default function AutomationSection() {
  const {
    eventTypes,
    webhooks,
    webhooksError,
    newWebhookUrl,
    setNewWebhookUrl,
    newWebhookEvents,
    setNewWebhookEvents,
    rules,
    rulesError,
    newRuleName,
    setNewRuleName,
    newRuleTrigger,
    setNewRuleTrigger,
    newRuleFolderId,
    setNewRuleFolderId,
    newRuleActionType,
    setNewRuleActionType,
    newRulePrompt,
    setNewRulePrompt,
    newRuleMode,
    setNewRuleMode,
    newRuleWebhookUrl,
    setNewRuleWebhookUrl,
    addWebhook,
    toggleWebhook,
    deleteWebhook,
    addRule,
    toggleRule,
    deleteRule,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Webhooks</h3>
      <p className="settings-section-desc">
        POST a small JSON payload to a URL on your own machine when something real
        happens — a digest is generated, a schedule finishes, an urgent email is
        flagged, a memory conflict is found, or a watched folder gets a new file.
      </p>
      <div className="setting-row setting-row-stack">
        <input
          className="settings-input"
          placeholder="http://localhost:9000/hook"
          aria-label="Webhook URL"
          value={newWebhookUrl}
          onChange={(e) => setNewWebhookUrl(e.target.value)}
        />
        <div className="settings-row" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
          {eventTypes.map((t) => (
            <label key={t} style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "var(--text-xs)" }}>
              <input
                type="checkbox"
                checked={newWebhookEvents.includes(t)}
                onChange={(e) =>
                  setNewWebhookEvents((evs) =>
                    e.target.checked ? [...evs, t] : evs.filter((x) => x !== t)
                  )
                }
              />
              {t}
            </label>
          ))}
        </div>
        <button className="settings-btn-primary" onClick={addWebhook} style={{ alignSelf: "flex-end" }}>
          Add webhook
        </button>
      </div>
      {webhooksError && <p className="settings-error">{webhooksError}</p>}
      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {webhooks.map((w) => (
          <li key={w.id} style={{ opacity: w.enabled ? 1 : 0.5 }}>
            <span className="model-name" style={{ flex: 1 }}>
              {w.url}
              <span className="setting-hint" style={{ display: "block" }}>{w.event_types.join(", ")}</span>
            </span>
            <span className="settings-row" style={{ gap: "0.5rem" }}>
              <button className="text-btn" onClick={() => toggleWebhook(w.id, !w.enabled)}>
                {w.enabled ? "On" : "Off"}
              </button>
              <button className="icon-btn" onClick={() => deleteWebhook(w.id)} title="Delete" aria-label="Delete webhook">×</button>
            </span>
          </li>
        ))}
        {webhooks.length === 0 && !webhooksError && <li className="model-empty">No webhooks yet.</li>}
      </ul>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>Automation rules</h3>
      <p className="settings-section-desc">
        Trigger -&gt; action, on top of the same events webhooks use. A "prompt" action
        sends a message into a persistent conversation (chat/research mode only —
        never agent, same reason schedules never run unattended agent turns). Use
        <code>{"{event_data}"}</code> in the prompt to reference what happened.
      </p>
      <div className="setting-row setting-row-stack">
        <div className="settings-row">
          <input
            className="settings-input"
            placeholder="Rule name"
            aria-label="Rule name"
            value={newRuleName}
            onChange={(e) => setNewRuleName(e.target.value)}
          />
          <select className="settings-select" value={newRuleTrigger} onChange={(e) => setNewRuleTrigger(e.target.value)} aria-label="Rule trigger event">
            {eventTypes.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        {newRuleTrigger === "folder_file_added" && (
          <input
            className="settings-input"
            placeholder="Folder ID to filter on (optional — leave blank for any watched folder)"
            aria-label="Folder ID to filter on"
            value={newRuleFolderId}
            onChange={(e) => setNewRuleFolderId(e.target.value)}
          />
        )}
        <select className="settings-select" value={newRuleActionType} onChange={(e) => setNewRuleActionType(e.target.value)} aria-label="Rule action type">
          <option value="prompt">Send a prompt</option>
          <option value="webhook">Call a webhook</option>
        </select>
        {newRuleActionType === "prompt" ? (
          <>
            <textarea
              className="settings-textarea"
              rows={2}
              placeholder="Prompt to run, e.g. Summarize this: {event_data}"
              aria-label="Prompt to run"
              value={newRulePrompt}
              onChange={(e) => setNewRulePrompt(e.target.value)}
            />
            <select className="settings-select" value={newRuleMode} onChange={(e) => setNewRuleMode(e.target.value)} aria-label="Rule mode">
              <option value="chat">Chat</option>
              <option value="research">Deep Research</option>
            </select>
          </>
        ) : (
          <input
            className="settings-input"
            placeholder="Webhook URL for this rule"
            aria-label="Webhook URL for this rule"
            value={newRuleWebhookUrl}
            onChange={(e) => setNewRuleWebhookUrl(e.target.value)}
          />
        )}
        <button className="settings-btn-primary" onClick={addRule} style={{ alignSelf: "flex-end" }}>
          Add rule
        </button>
      </div>
      {rulesError && <p className="settings-error">{rulesError}</p>}
      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {rules.map((r) => (
          <li key={r.id} style={{ opacity: r.enabled ? 1 : 0.5 }}>
            <span className="model-name" style={{ flex: 1 }}>
              {r.name}
              <span className="setting-hint" style={{ display: "block" }}>
                {r.trigger_type} → {r.action_type}
                {r.last_fired_at ? ` · last fired ${new Date(r.last_fired_at * 1000).toLocaleString()}` : " · never fired"}
              </span>
            </span>
            <span className="settings-row" style={{ gap: "0.5rem" }}>
              <button className="text-btn" onClick={() => toggleRule(r.id, !r.enabled)}>
                {r.enabled ? "On" : "Off"}
              </button>
              <button className="icon-btn" onClick={() => deleteRule(r.id)} title="Delete" aria-label="Delete rule">×</button>
            </span>
          </li>
        ))}
        {rules.length === 0 && !rulesError && <li className="model-empty">No automation rules yet.</li>}
      </ul>
    </section>
  );
}
