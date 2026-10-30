import { api } from "../../lib/api";
import { useSettings } from "./SettingsContext.js";

/** Settings → "memory" section. State lives in SettingsPanel (see SettingsContext). */
export default function MemorySection() {
  const {
    config,
    setConfig,
    memories,
    memoriesError,
    memoryConflicts,
    reviewingConflicts,
    newMemory,
    setNewMemory,
    systemPrompt,
    setSystemPrompt,
    promptSaving,
    promptSaved,
    reviewMemoryConflicts,
    resolveMemoryConflict,
    saveSystemPrompt,
    toggleMemoryEnabled,
    toggleRecallEnabled,
    addMemory,
    toggleMemory,
    deleteMemory,
    clearAllMemories,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Persona</h3>
      <p className="settings-section-desc">
        Standing instructions sent with every message — tone, role, how you want
        Zenith to behave. Applies regardless of which model the router picks.
      </p>
      <div className="setting-row setting-row-stack">
        <textarea
          className="settings-textarea"
          rows={4}
          placeholder="e.g. Be terse. Prefer metric units. I'm a backend engineer, skip basic explanations."
          aria-label="Persona instructions"
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
        />
        <div className="settings-row">
          <button className="settings-btn-primary" onClick={saveSystemPrompt} disabled={promptSaving}>
            {promptSaving ? "Saving…" : promptSaved ? "Saved ✓" : "Save"}
          </button>
        </div>
      </div>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Long-term memory
      </h3>
      <p className="settings-section-desc">
        Zenith quietly picks up durable facts from what you say ("uses fish shell",
        "allergic to peanuts") and recalls them in future chats. Nothing leaves your
        machine.
      </p>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Remember facts automatically</span>
          <span className="setting-hint">Extracts durable facts from your messages.</span>
        </div>
        <button
          className={`switch ${config?.memory_enabled ? "switch-on" : ""}`}
          onClick={() => toggleMemoryEnabled(!config?.memory_enabled)}
          role="switch"
          aria-checked={!!config?.memory_enabled}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Daily digest</span>
          <span className="setting-hint">
            Unprompted "what changed" summary from watched folders + new memories, once
            a day in the background. Generate one manually any time from the sun icon.
          </span>
        </div>
        <button
          className={`switch ${config?.digest_enabled ? "switch-on" : ""}`}
          onClick={async () => setConfig(await api.patchConfig({ digest_enabled: !config?.digest_enabled }))}
          role="switch"
          aria-checked={!!config?.digest_enabled}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Recall past conversations</span>
          <span className="setting-hint">
            Surfaces relevant excerpts from other chats when they seem relevant.
          </span>
        </div>
        <button
          className={`switch ${config?.recall_enabled ? "switch-on" : ""}`}
          onClick={() => toggleRecallEnabled(!config?.recall_enabled)}
          role="switch"
          aria-checked={!!config?.recall_enabled}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      {memoryConflicts.length > 0 && (
        <div className="settings-notice settings-notice-warn" style={{ marginTop: "1rem" }}>
          <strong>{memoryConflicts.length} possible contradiction{memoryConflicts.length === 1 ? "" : "s"}</strong>
          <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.1rem" }}>
            {memoryConflicts.map((c) => (
              <li key={c.id} style={{ marginBottom: "0.4rem" }}>
                "{c.memory_a.content}" vs "{c.memory_b.content}" — {c.reason}
                <button
                  className="text-btn"
                  style={{ marginLeft: "0.5rem" }}
                  onClick={() => resolveMemoryConflict(c.id)}
                >
                  Dismiss
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="settings-row" style={{ marginTop: "0.5rem" }}>
        <button className="text-btn" onClick={reviewMemoryConflicts} disabled={reviewingConflicts}>
          {reviewingConflicts ? "Reviewing…" : "Review for contradictions"}
        </button>
      </div>

      <div className="settings-row" style={{ marginTop: "1rem" }}>
        <input
          className="settings-input"
          placeholder="Add a memory manually…"
          aria-label="Add a memory manually"
          value={newMemory}
          onChange={(e) => setNewMemory(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addMemory()}
        />
        <button className="settings-btn-primary" onClick={addMemory}>
          Add
        </button>
      </div>
      {memoriesError && <p className="settings-error">{memoriesError}</p>}

      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {memories.map((m) => (
          <li key={m.id} style={{ opacity: m.enabled ? 1 : 0.45 }}>
            <span className="model-name" style={{ flex: 1 }}>
              {m.content}
            </span>
            <span className="settings-row" style={{ gap: "0.5rem" }}>
              <button
                className="text-btn"
                onClick={() => toggleMemory(m.id, !m.enabled)}
                title={m.enabled ? "Disable" : "Enable"}
              >
                {m.enabled ? "On" : "Off"}
              </button>
              <button className="icon-btn" onClick={() => deleteMemory(m.id)} title="Forget" aria-label="Forget">
                ×
              </button>
            </span>
          </li>
        ))}
        {memories.length === 0 && !memoriesError && (
          <li className="model-empty">Nothing remembered yet.</li>
        )}
      </ul>
      {memories.length > 0 && (
        <div className="settings-row" style={{ marginTop: "0.5rem" }}>
          <button className="text-btn" onClick={clearAllMemories}>
            Forget everything
          </button>
        </div>
      )}
    </section>
  );
}
