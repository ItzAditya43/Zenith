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
  { id: "memory", label: "Memory & persona", icon: "◆" },
  { id: "personas", label: "Personas", icon: "🎭" },
  { id: "agent", label: "Agent tools", icon: "🤖" },
  { id: "council", label: "Council", icon: "👥" },
  { id: "routing", label: "Model routing", icon: "⇄" },
  { id: "models", label: "Installed models", icon: "▦" },
  { id: "voice", label: "Voice & audio", icon: "🎙" },
  { id: "data", label: "Data", icon: "⬇" },
  { id: "folders", label: "Folders", icon: "📁" },
  { id: "schedules", label: "Schedules", icon: "⏱" },
];

export default function SettingsPanel({ onClose, theme, onThemeChange, voiceReplyEnabled, onVoiceReplyChange }) {
  const [config, setConfig] = useState(null);
  const [models, setModels] = useState([]);
  const [modelsError, setModelsError] = useState(null);
  const [host, setHost] = useState("");
  const [saving, setSaving] = useState(false);
  const [activeSection, setActiveSection] = useState("appearance");
  const [memories, setMemories] = useState([]);
  const [memoriesError, setMemoriesError] = useState(null);
  const [personas, setPersonas] = useState([]);
  const [newPersonaName, setNewPersonaName] = useState("");
  const [newPersonaIcon, setNewPersonaIcon] = useState("");
  const [newPersonaPrompt, setNewPersonaPrompt] = useState("");
  const [personasError, setPersonasError] = useState(null);
  const [folders, setFolders] = useState([]);
  const [foldersError, setFoldersError] = useState(null);
  const [newFolderPath, setNewFolderPath] = useState("");
  const [scanningFolder, setScanningFolder] = useState(null);
  const [schedules, setSchedules] = useState([]);
  const [schedulesError, setSchedulesError] = useState(null);
  const [newScheduleName, setNewScheduleName] = useState("");
  const [newSchedulePrompt, setNewSchedulePrompt] = useState("");
  const [newScheduleMode, setNewScheduleMode] = useState("chat");
  const [newScheduleInterval, setNewScheduleInterval] = useState(1440);
  const [runningSchedule, setRunningSchedule] = useState(null);
  const [expandedSchedule, setExpandedSchedule] = useState(null);
  const [scheduleRuns, setScheduleRuns] = useState({});
  const [mcpServers, setMcpServers] = useState([]);
  const [mcpError, setMcpError] = useState(null);
  const [newMcpName, setNewMcpName] = useState("");
  const [newMcpCommand, setNewMcpCommand] = useState("");
  const [newMcpArgs, setNewMcpArgs] = useState("");
  const [mcpToolsChecking, setMcpToolsChecking] = useState(null);
  const [mcpToolsResult, setMcpToolsResult] = useState({});
  const [newMemory, setNewMemory] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptSaving, setPromptSaving] = useState(false);
  const [promptSaved, setPromptSaved] = useState(false);

  const refreshMemories = () => {
    api
      .listMemories()
      .then((m) => {
        setMemories(m);
        setMemoriesError(null);
      })
      .catch((err) => setMemoriesError(err.message));
  };

  const refreshModels = () => {
    api
      .listModels()
      .then((m) => {
        setModels(m);
        setModelsError(null);
      })
      .catch((err) => setModelsError(err.message));
  };

  const refreshPersonas = () => {
    api
      .listPersonas()
      .then((p) => {
        setPersonas(p);
        setPersonasError(null);
      })
      .catch((err) => setPersonasError(err.message));
  };

  const refreshFolders = () => {
    api
      .listFolders()
      .then((f) => {
        setFolders(f);
        setFoldersError(null);
      })
      .catch((err) => setFoldersError(err.message));
  };

  useEffect(() => {
    api.getConfig().then((c) => {
      setConfig(c);
      setHost(c.ollama_host);
      setSystemPrompt(c.system_prompt || "");
    });
    refreshModels();
    refreshMemories();
    refreshPersonas();
    refreshFolders();
    refreshSchedules();
    refreshMcpServers();
  }, []);

  const refreshMcpServers = () => {
    api
      .listMcpServers()
      .then((s) => {
        setMcpServers(s);
        setMcpError(null);
      })
      .catch((err) => setMcpError(err.message));
  };

  const addMcpServer = async () => {
    if (!newMcpName.trim() || !newMcpCommand.trim()) return;
    try {
      const args = newMcpArgs.trim() ? newMcpArgs.trim().split(/\s+/) : [];
      await api.addMcpServer(newMcpName.trim(), newMcpCommand.trim(), args);
      setNewMcpName("");
      setNewMcpCommand("");
      setNewMcpArgs("");
      refreshMcpServers();
    } catch (err) {
      setMcpError(err.message);
    }
  };

  const removeMcpServer = async (id) => {
    await api.removeMcpServer(id);
    refreshMcpServers();
  };

  const toggleMcpServer = async (id, enabled) => {
    setMcpServers((s) => s.map((x) => (x.id === id ? { ...x, enabled: enabled ? 1 : 0 } : x)));
    await api.toggleMcpServer(id, enabled);
  };

  const checkMcpTools = async (id) => {
    setMcpToolsChecking(id);
    try {
      const tools = await api.getMcpServerTools(id);
      setMcpToolsResult((r) => ({ ...r, [id]: tools }));
    } catch (err) {
      setMcpToolsResult((r) => ({ ...r, [id]: { error: err.message } }));
    } finally {
      setMcpToolsChecking(null);
    }
  };

  const refreshSchedules = () => {
    api
      .listSchedules()
      .then((s) => {
        setSchedules(s);
        setSchedulesError(null);
      })
      .catch((err) => setSchedulesError(err.message));
  };

  const addSchedule = async () => {
    if (!newScheduleName.trim() || !newSchedulePrompt.trim()) return;
    try {
      await api.createSchedule(newScheduleName.trim(), newSchedulePrompt.trim(), newScheduleMode, Number(newScheduleInterval));
      setNewScheduleName("");
      setNewSchedulePrompt("");
      refreshSchedules();
    } catch (err) {
      setSchedulesError(err.message);
    }
  };

  const deleteSchedule = async (id) => {
    await api.deleteSchedule(id);
    refreshSchedules();
  };

  const toggleSchedule = async (id, enabled) => {
    setSchedules((s) => s.map((x) => (x.id === id ? { ...x, enabled: enabled ? 1 : 0 } : x)));
    await api.toggleSchedule(id, enabled);
  };

  const runScheduleNow = async (id) => {
    setRunningSchedule(id);
    try {
      await api.runScheduleNow(id);
      refreshSchedules();
      if (expandedSchedule === id) {
        setScheduleRuns((r) => ({ ...r, [id]: undefined }));
        toggleExpandSchedule(id, true);
      }
    } catch (err) {
      setSchedulesError(err.message);
    } finally {
      setRunningSchedule(null);
    }
  };

  const toggleExpandSchedule = async (id, forceOpen = false) => {
    if (expandedSchedule === id && !forceOpen) {
      setExpandedSchedule(null);
      return;
    }
    setExpandedSchedule(id);
    if (!scheduleRuns[id] || forceOpen) {
      const runs = await api.listScheduleRuns(id);
      setScheduleRuns((r) => ({ ...r, [id]: runs }));
    }
  };

  const addFolder = async () => {
    if (!newFolderPath.trim()) return;
    try {
      await api.addFolder(newFolderPath.trim());
      setNewFolderPath("");
      refreshFolders();
    } catch (err) {
      setFoldersError(err.message);
    }
  };

  const removeFolder = async (id) => {
    await api.removeFolder(id);
    refreshFolders();
  };

  const toggleFolder = async (id, enabled) => {
    setFolders((fs) => fs.map((f) => (f.id === id ? { ...f, enabled: enabled ? 1 : 0 } : f)));
    await api.toggleFolder(id, enabled);
  };

  const scanFolderNow = async (id) => {
    setScanningFolder(id);
    try {
      const result = await api.scanFolderNow(id);
      setFoldersError(
        result.errors?.length
          ? `Scanned ${result.scanned}, indexed ${result.indexed}, ${result.errors.length} error(s).`
          : null
      );
      refreshFolders();
    } catch (err) {
      setFoldersError(err.message);
    } finally {
      setScanningFolder(null);
    }
  };

  const addPersona = async () => {
    if (!newPersonaName.trim() || !newPersonaPrompt.trim()) return;
    try {
      await api.createPersona(newPersonaName.trim(), newPersonaPrompt.trim(), newPersonaIcon.trim() || null);
      setNewPersonaName("");
      setNewPersonaIcon("");
      setNewPersonaPrompt("");
      refreshPersonas();
    } catch (err) {
      setPersonasError(err.message);
    }
  };

  const deletePersona = async (id) => {
    await api.deletePersona(id);
    refreshPersonas();
  };

  const saveSystemPrompt = async () => {
    setPromptSaving(true);
    const updated = await api.patchConfig({ system_prompt: systemPrompt });
    setConfig(updated);
    setPromptSaving(false);
    setPromptSaved(true);
    setTimeout(() => setPromptSaved(false), 1500);
  };

  const toggleMemoryEnabled = async (checked) => {
    const updated = await api.patchConfig({ memory_enabled: checked });
    setConfig(updated);
  };

  const toggleRecallEnabled = async (checked) => {
    const updated = await api.patchConfig({ recall_enabled: checked });
    setConfig(updated);
  };

  const toggleAgentEnabled = async (checked) => {
    const updated = await api.patchConfig({ agent_enabled: checked });
    setConfig(updated);
  };

  const setAgentMode = async (mode) => {
    const updated = await api.patchConfig({ agent_mode: mode });
    setConfig(updated);
  };

  const addMemory = async () => {
    const text = newMemory.trim();
    if (!text) return;
    try {
      await api.addMemory(text);
      setNewMemory("");
      refreshMemories();
    } catch (err) {
      setMemoriesError(err.message);
    }
  };

  const toggleMemory = async (id, enabled) => {
    setMemories((ms) => ms.map((m) => (m.id === id ? { ...m, enabled: enabled ? 1 : 0 } : m)));
    await api.toggleMemory(id, enabled);
  };

  const deleteMemory = async (id) => {
    setMemories((ms) => ms.filter((m) => m.id !== id));
    await api.deleteMemory(id);
  };

  const clearAllMemories = async () => {
    if (!window.confirm("Forget everything Cortex has learned about you? This can't be undone."))
      return;
    await api.clearMemories();
    refreshMemories();
  };

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

            {activeSection === "memory" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Persona</h3>
                <p className="settings-section-desc">
                  Standing instructions sent with every message — tone, role, how you want
                  Cortex to behave. Applies regardless of which model the router picks.
                </p>
                <div className="setting-row setting-row-stack">
                  <textarea
                    className="settings-textarea"
                    rows={4}
                    placeholder="e.g. Be terse. Prefer metric units. I'm a backend engineer, skip basic explanations."
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
                  Cortex quietly picks up durable facts from what you say ("uses fish shell",
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

                <div className="settings-row" style={{ marginTop: "1rem" }}>
                  <input
                    className="settings-input"
                    placeholder="Add a memory manually…"
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
                        <button className="icon-btn" onClick={() => deleteMemory(m.id)} title="Forget">
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
            )}

            {activeSection === "personas" && (
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
                      placeholder="🎭"
                      value={newPersonaIcon}
                      onChange={(e) => setNewPersonaIcon(e.target.value)}
                      maxLength={4}
                    />
                    <input
                      className="settings-input"
                      placeholder="Name, e.g. Coding buddy"
                      value={newPersonaName}
                      onChange={(e) => setNewPersonaName(e.target.value)}
                    />
                  </div>
                  <textarea
                    className="settings-textarea"
                    rows={3}
                    placeholder="System prompt for this persona…"
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
                      <button className="icon-btn" onClick={() => deletePersona(p.id)} title="Delete">
                        ×
                      </button>
                    </li>
                  ))}
                  {personas.length === 0 && !personasError && (
                    <li className="model-empty">No personas yet — add one above.</li>
                  )}
                </ul>
              </section>
            )}

            {activeSection === "agent" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Agent tools</h3>
                <p className="settings-section-desc">
                  Off by default. When on, Cortex can run shell commands and read/write files
                  across multiple steps to complete a request — not just answer from context.
                  This runs with the same permissions as the backend process, on whatever
                  filesystem it can see (the container's, unless you've bind-mounted your real
                  host into docker-compose.yml). Only enable this if you understand what that
                  means.
                </p>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Enable agent tools</span>
                    <span className="setting-hint">
                      Master switch. Off = the 🤖 composer toggle does nothing.
                    </span>
                  </div>
                  <button
                    className={`switch ${config?.agent_enabled ? "switch-on" : ""}`}
                    onClick={() => toggleAgentEnabled(!config?.agent_enabled)}
                    role="switch"
                    aria-checked={!!config?.agent_enabled}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>

                <div className="setting-row setting-row-stack">
                  <label className="setting-label" htmlFor="agent-mode">
                    Autonomy
                  </label>
                  <select
                    id="agent-mode"
                    className="settings-select"
                    value={config?.agent_mode || "manual"}
                    onChange={(e) => setAgentMode(e.target.value)}
                    disabled={!config?.agent_enabled}
                  >
                    <option value="manual">Manual — approve every action</option>
                    <option value="semi">Semi-auto — auto-run reads, confirm writes</option>
                    <option value="full">Full-auto — no confirmation</option>
                  </select>
                  <span className="setting-hint">
                    {config?.agent_mode === "full"
                      ? "Nothing pauses for approval. Only as safe as your prompts."
                      : config?.agent_mode === "semi"
                      ? "Read-only calls (read/list/search) run immediately; writes and shell commands with side effects still ask first."
                      : "Every tool call — even a plain file read — shows up in chat for you to approve or deny."}
                  </span>
                </div>

                <p className="settings-hint-note">
                  Small models (roughly under ~4B parameters) often skip the tool-calling
                  protocol entirely and answer from guesswork instead of actually using a tool —
                  this isn't a bug in Cortex, it's a real limitation of small local models. Pin
                  the "general" role to a larger model in Model routing for agent turns to work
                  reliably.
                </p>

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  MCP servers
                </h3>
                <p className="settings-section-desc">
                  Connect external MCP (Model Context Protocol) tool servers — email, calendar,
                  Notion, whatever's published — instead of Cortex hand-building each
                  integration. Runs as a local subprocess over stdio, same free-by-construction
                  posture as everything else here. Their tools appear in agent mode's tool list
                  automatically, prefixed <code>mcp__servername__</code>, and go through the same
                  approval gate as bash/write_file (external tools are unknown behavior, so
                  they're always classified risky).
                </p>

                <div className="settings-row">
                  <input
                    className="settings-input"
                    placeholder="Name"
                    value={newMcpName}
                    onChange={(e) => setNewMcpName(e.target.value)}
                    style={{ flex: "0 0 120px" }}
                  />
                  <input
                    className="settings-input"
                    placeholder="Command, e.g. npx or /path/to/python"
                    value={newMcpCommand}
                    onChange={(e) => setNewMcpCommand(e.target.value)}
                  />
                  <input
                    className="settings-input"
                    placeholder="Args (space-separated)"
                    value={newMcpArgs}
                    onChange={(e) => setNewMcpArgs(e.target.value)}
                  />
                  <button className="settings-btn-primary" onClick={addMcpServer}>
                    Add
                  </button>
                </div>
                {mcpError && <p className="settings-error">{mcpError}</p>}

                <ul className="model-list" style={{ marginTop: "0.75rem" }}>
                  {mcpServers.map((s) => (
                    <li key={s.id} style={{ flexDirection: "column", alignItems: "stretch", opacity: s.enabled ? 1 : 0.5 }}>
                      <div className="settings-row settings-row-space-between">
                        <span className="model-name" style={{ flex: 1 }}>
                          {s.name}
                          <span className="setting-hint" style={{ display: "block", fontFamily: "var(--font-mono)" }}>
                            {s.command} {s.args.join(" ")}
                          </span>
                        </span>
                        <span className="settings-row" style={{ gap: "0.5rem" }}>
                          <button className="text-btn" onClick={() => checkMcpTools(s.id)}>
                            {mcpToolsChecking === s.id ? "Checking…" : "Test connection"}
                          </button>
                          <button className="text-btn" onClick={() => toggleMcpServer(s.id, !s.enabled)}>
                            {s.enabled ? "On" : "Off"}
                          </button>
                          <button className="icon-btn" onClick={() => removeMcpServer(s.id)} title="Remove">
                            ×
                          </button>
                        </span>
                      </div>
                      {mcpToolsResult[s.id] && (
                        <div className="tool-call-body" style={{ padding: "0.5rem 0 0" }}>
                          {mcpToolsResult[s.id].error ? (
                            <span className="settings-error">{mcpToolsResult[s.id].error}</span>
                          ) : mcpToolsResult[s.id].length === 0 ? (
                            <span className="setting-hint">Connected, but no tools advertised.</span>
                          ) : (
                            mcpToolsResult[s.id].map((t) => (
                              <pre key={t.name} className="tool-call-result" style={{ marginBottom: "0.3rem" }}>
                                {t.name}: {t.description}
                              </pre>
                            ))
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                  {mcpServers.length === 0 && !mcpError && (
                    <li className="model-empty">No MCP servers configured.</li>
                  )}
                </ul>
              </section>
            )}

            {activeSection === "council" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Council of models</h3>
                <p className="settings-section-desc">
                  Pick 2 or more installed models. When the 👥 toggle in the composer is on,
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

            {activeSection === "data" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Data</h3>
                <p className="settings-section-desc">
                  Everything Cortex knows about you, in a format you can actually read and keep
                  — no lock-in. Downloads run locally against your own backend.
                </p>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Export as JSON</span>
                    <span className="setting-hint">
                      Complete, machine-readable — every conversation, message, memory, and
                      persona.
                    </span>
                  </div>
                  <a className="settings-btn-primary" href={api.exportUrl("json")} download>
                    Download .json
                  </a>
                </div>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Export as Markdown</span>
                    <span className="setting-hint">
                      One readable .md file per conversation, zipped — good for archiving or
                      reading outside Cortex.
                    </span>
                  </div>
                  <a className="settings-btn-primary" href={api.exportUrl("markdown")} download>
                    Download .zip
                  </a>
                </div>
              </section>
            )}

            {activeSection === "folders" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Watched folders</h3>
                <p className="settings-section-desc">
                  Point Cortex at a folder and it periodically re-indexes matching files
                  (.md/.txt/.py/.js/.ts/.json) so their content is recalled in chat automatically
                  — no manual upload per file. Paths are resolved on the <em>backend</em>, which
                  in the Docker deployment means the container's own filesystem unless you've
                  added a host bind mount in docker-compose.yml.
                </p>

                <div className="settings-row">
                  <input
                    className="settings-input"
                    placeholder="/path/to/notes"
                    value={newFolderPath}
                    onChange={(e) => setNewFolderPath(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addFolder()}
                  />
                  <button className="settings-btn-primary" onClick={addFolder}>
                    Watch
                  </button>
                </div>
                {foldersError && <p className="settings-error">{foldersError}</p>}

                <ul className="model-list" style={{ marginTop: "0.75rem" }}>
                  {folders.map((f) => (
                    <li key={f.id} style={{ opacity: f.enabled ? 1 : 0.5 }}>
                      <span className="model-name" style={{ flex: 1 }}>
                        {f.path}
                        <span className="setting-hint" style={{ display: "block" }}>
                          {f.last_scanned_at
                            ? `Last scanned ${new Date(f.last_scanned_at * 1000).toLocaleString()}`
                            : "Not scanned yet"}
                        </span>
                      </span>
                      <span className="settings-row" style={{ gap: "0.5rem" }}>
                        <button
                          className="text-btn"
                          onClick={() => scanFolderNow(f.id)}
                          disabled={scanningFolder === f.id}
                        >
                          {scanningFolder === f.id ? "Scanning…" : "Scan now"}
                        </button>
                        <button className="text-btn" onClick={() => toggleFolder(f.id, !f.enabled)}>
                          {f.enabled ? "On" : "Off"}
                        </button>
                        <button className="icon-btn" onClick={() => removeFolder(f.id)} title="Stop watching">
                          ×
                        </button>
                      </span>
                    </li>
                  ))}
                  {folders.length === 0 && !foldersError && (
                    <li className="model-empty">No folders watched yet.</li>
                  )}
                </ul>
              </section>
            )}

            {activeSection === "schedules" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Scheduled turns</h3>
                <p className="settings-section-desc">
                  "Every morning, research X and summarize" without touching the keyboard. Each
                  schedule gets its own conversation that keeps a running log across runs.
                  Restricted to Chat and Deep Research modes — never Agent — since an unattended
                  cron job running shell commands with nobody there to approve it is a real
                  escalation, not a formality.
                </p>

                <div className="setting-row setting-row-stack">
                  <div className="settings-row">
                    <input
                      className="settings-input"
                      placeholder="Name, e.g. Morning brief"
                      value={newScheduleName}
                      onChange={(e) => setNewScheduleName(e.target.value)}
                    />
                    <select
                      className="settings-select"
                      style={{ flex: "0 0 140px" }}
                      value={newScheduleMode}
                      onChange={(e) => setNewScheduleMode(e.target.value)}
                    >
                      <option value="chat">Chat</option>
                      <option value="research">Deep Research</option>
                    </select>
                  </div>
                  <textarea
                    className="settings-textarea"
                    rows={2}
                    placeholder="Prompt to run each time…"
                    value={newSchedulePrompt}
                    onChange={(e) => setNewSchedulePrompt(e.target.value)}
                  />
                  <div className="settings-row">
                    <label className="setting-label" htmlFor="sched-interval" style={{ flexShrink: 0 }}>
                      Every
                    </label>
                    <select
                      id="sched-interval"
                      className="settings-select"
                      value={newScheduleInterval}
                      onChange={(e) => setNewScheduleInterval(e.target.value)}
                    >
                      <option value={60}>hour</option>
                      <option value={360}>6 hours</option>
                      <option value={1440}>day</option>
                      <option value={10080}>week</option>
                    </select>
                    <button className="settings-btn-primary" onClick={addSchedule}>
                      Add schedule
                    </button>
                  </div>
                </div>
                {schedulesError && <p className="settings-error">{schedulesError}</p>}

                <ul className="model-list" style={{ marginTop: "0.75rem" }}>
                  {schedules.map((s) => (
                    <li key={s.id} style={{ flexDirection: "column", alignItems: "stretch", opacity: s.enabled ? 1 : 0.5 }}>
                      <div className="settings-row settings-row-space-between">
                        <span className="model-name" style={{ flex: 1 }}>
                          {s.name}
                          <span className="setting-hint" style={{ display: "block" }}>
                            {s.mode} · every {s.interval_minutes} min
                            {s.last_run_at ? ` · last run ${new Date(s.last_run_at * 1000).toLocaleString()}` : " · never run"}
                          </span>
                        </span>
                        <span className="settings-row" style={{ gap: "0.5rem" }}>
                          <button
                            className="text-btn"
                            onClick={() => runScheduleNow(s.id)}
                            disabled={runningSchedule === s.id}
                          >
                            {runningSchedule === s.id ? "Running…" : "Run now"}
                          </button>
                          <button className="text-btn" onClick={() => toggleExpandSchedule(s.id)}>
                            History
                          </button>
                          <button className="text-btn" onClick={() => toggleSchedule(s.id, !s.enabled)}>
                            {s.enabled ? "On" : "Off"}
                          </button>
                          <button className="icon-btn" onClick={() => deleteSchedule(s.id)} title="Delete">
                            ×
                          </button>
                        </span>
                      </div>
                      {expandedSchedule === s.id && (
                        <div className="tool-call-body" style={{ padding: "0.5rem 0 0" }}>
                          {(scheduleRuns[s.id] || []).map((r) => (
                            <pre key={r.id} className="tool-call-result" style={{ marginBottom: "0.4rem" }}>
                              {new Date(r.started_at * 1000).toLocaleString()} — {r.status}
                              {"\n"}
                              {r.status === "error" ? r.error : r.summary}
                            </pre>
                          ))}
                          {(scheduleRuns[s.id] || []).length === 0 && (
                            <span className="setting-hint">No runs yet.</span>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                  {schedules.length === 0 && !schedulesError && (
                    <li className="model-empty">No schedules yet.</li>
                  )}
                </ul>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}