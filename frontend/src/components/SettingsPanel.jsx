import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import { ANIMATIONS, THEME_ANIMATIONS } from "../lib/ambientAnimations";

const THEMES = [
  { id: "midnight-glass", name: "Midnight Glass", bg: "#12151f", fg: "#dde1ea", accent: "#4dd9c0", font: "'Space Grotesk', sans-serif" },
  { id: "terminal-noir", name: "Terminal Noir", bg: "#081008", fg: "#b8ffce", accent: "#58ff8a", font: "'JetBrains Mono', monospace" },
  { id: "command-center", name: "Command Center", bg: "#0b1319", fg: "#d6e4ec", accent: "#00d9ff", font: "'JetBrains Mono', monospace" },
  { id: "deep-space", name: "Deep Space", bg: "#0a0a16", fg: "#e8e6ff", accent: "#7b6cff", font: "'Space Grotesk', sans-serif" },
  { id: "brutalist-mono", name: "Brutalist Mono", bg: "#f2f2f0", fg: "#0a0a0a", accent: "#0a0a0a", font: "'IBM Plex Mono', monospace" },
  { id: "zen-minimal", name: "Zen Minimal", bg: "#ffffff", fg: "#1c1c1c", accent: "#1c1c1c", font: "'Inter', sans-serif" },
  { id: "cyber-grid", name: "Cyber Grid", bg: "#0e0a17", fg: "#f0e9ff", accent: "#00fff7", font: "'JetBrains Mono', monospace" },
  { id: "slate", name: "Slate", bg: "#17181c", fg: "#e4e5e8", accent: "#8f97a3", font: "'Inter', sans-serif" },
];

const FIT_RANK = { comfortable: 0, tight: 1, unknown: 2, will_struggle: 3 };

/** Task filter chips for the "models" settings section — maps a friendly
 * label to the underlying COOKBOOK/CLOUD_COOKBOOK `role` value. */
const MODEL_TASK_FILTERS = [
  { key: "all", label: "All" },
  { key: "general", label: "Chat" },
  { key: "code", label: "Code" },
  { key: "vision", label: "Vision" },
  { key: "reasoning", label: "Reasoning" },
  { key: "small_fast", label: "Quick replies" },
];

/** Best already-installed, role-matching model for this hardware: prefer
 * a better fit tier, then (within the same tier) the biggest model —
 * more capable is better as long as it still comfortably fits. Returns
 * null if nothing tagged for the role or no hardware report yet. */
function recommendedModelForRole(role, models, hardware) {
  if (!hardware?.installed?.length) return null;
  const fitByName = Object.fromEntries(hardware.installed.map((m) => [m.name, m]));
  const candidates = models
    .filter((m) => m.roles?.includes(role))
    .map((m) => ({ name: m.name, ...fitByName[m.name] }))
    .filter((m) => m.fit);
  if (!candidates.length) return null;
  candidates.sort((a, b) => {
    const rankDiff = (FIT_RANK[a.fit] ?? 9) - (FIT_RANK[b.fit] ?? 9);
    if (rankDiff !== 0) return rankDiff;
    return (b.params_b || 0) - (a.params_b || 0);
  });
  return candidates[0];
}

// A curated starting point, not a live directory — the MCP ecosystem has
// no central registry, so this is deliberately a short, hand-picked list
// of well-known, keyless (no API account needed) servers that match
// Zenith's "free by construction" posture, not an attempt at completeness.
const POPULAR_MCP_SERVERS = [
  {
    name: "filesystem", command: "npx", args: "-y @modelcontextprotocol/server-filesystem /path/to/allow",
    description: "Read/write access to a specific directory you choose — replace /path/to/allow before adding.",
  },
  {
    name: "fetch", command: "npx", args: "-y @modelcontextprotocol/server-fetch",
    description: "Fetch and read web pages as clean markdown/text.",
  },
  {
    name: "memory", command: "npx", args: "-y @modelcontextprotocol/server-memory",
    description: "A simple external knowledge-graph memory store, separate from Zenith's own memory.",
  },
  {
    name: "sequential-thinking", command: "npx", args: "-y @modelcontextprotocol/server-sequential-thinking",
    description: "Structured step-by-step reasoning scratchpad for harder problems.",
  },
  {
    name: "git", command: "uvx", args: "mcp-server-git",
    description: "Structured git operations via Python's uv — an alternative to Zenith's built-in git tool for a different repo.",
  },
];

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
  { id: "appearance", label: "Appearance", icon: "sun" },
  { id: "accessibility", label: "Accessibility", icon: "check" },
  { id: "connection", label: "Connection", icon: "bolt" },
  { id: "memory", label: "Memory & persona", icon: "layers" },
  { id: "personas", label: "Personas", icon: "masks" },
  { id: "agent", label: "Agent tools", icon: "bot" },
  { id: "skills", label: "Skills", icon: "bolt" },
  { id: "email", label: "Email", icon: "at-sign" },
  { id: "sync", label: "Sync", icon: "share" },
  { id: "council", label: "Council", icon: "users" },
  { id: "routing", label: "Model routing", icon: "target" },
  { id: "models", label: "Installed models", icon: "grid" },
  { id: "voice", label: "Voice & audio", icon: "mic" },
  { id: "data", label: "Data", icon: "download" },
  { id: "folders", label: "Folders", icon: "folder" },
  { id: "schedules", label: "Schedules", icon: "clock" },
  { id: "automation", label: "Automation", icon: "wrench" },
  { id: "about", label: "About", icon: "info" },
];

export default function SettingsPanel({
  onClose,
  theme,
  onThemeChange,
  voiceReplyEnabled,
  onVoiceReplyChange,
  density,
  onDensityChange,
  ambientAnim,
  onAmbientChange,
  notificationsEnabled,
  onNotificationsChange,
  onImported,
  initialSection = "appearance",
  onUseSkill = () => {},
  fontScale = "1",
  onFontScaleChange = () => {},
  highContrast = false,
  onHighContrastChange = () => {},
  reduceMotion = false,
  onReduceMotionChange = () => {},
  dyslexiaFont = false,
  onDyslexiaFontChange = () => {},
  underlineLinks = false,
  onUnderlineLinksChange = () => {},
}) {
  const [config, setConfig] = useState(null);
  const [models, setModels] = useState([]);
  const [modelsError, setModelsError] = useState(null);
  const [host, setHost] = useState("");
  const [saving, setSaving] = useState(false);
  const [activeSection, setActiveSection] = useState(initialSection);
  const [memories, setMemories] = useState([]);
  const [memoriesError, setMemoriesError] = useState(null);
  const [memoryConflicts, setMemoryConflicts] = useState([]);
  const [reviewingConflicts, setReviewingConflicts] = useState(false);
  const [skills, setSkills] = useState([]);
  const [skillsError, setSkillsError] = useState(null);
  const [hardware, setHardware] = useState(null);
  const [modelTaskFilter, setModelTaskFilter] = useState("all");
  const [routingStatus, setRoutingStatus] = useState(null);
  const [overrideSummary, setOverrideSummary] = useState([]);
  const [emailForm, setEmailForm] = useState({
    email_imap_host: "", email_imap_port: 993, email_smtp_host: "", email_smtp_port: 587,
    email_username: "", email_password: "",
  });
  const [emailTestStatus, setEmailTestStatus] = useState(null);
  const [emailTesting, setEmailTesting] = useState(false);
  const [emailMessages, setEmailMessages] = useState([]);
  const [emailMessagesError, setEmailMessagesError] = useState(null);
  const [openEmailId, setOpenEmailId] = useState(null);
  const [emailDetail, setEmailDetail] = useState(null);
  const [emailDraft, setEmailDraft] = useState("");
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailResearch, setEmailResearch] = useState(null);
  const [syncPassphrase, setSyncPassphrase] = useState("");
  const [pairCode, setPairCode] = useState(null);
  const [pairExpiresIn, setPairExpiresIn] = useState(0);
  const [joinHost, setJoinHost] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [syncStatus, setSyncStatus] = useState(null);
  const [syncBusy, setSyncBusy] = useState(false);
  const [importBlobText, setImportBlobText] = useState("");
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
  const [eventTypes, setEventTypes] = useState([]);
  const [webhooks, setWebhooks] = useState([]);
  const [webhooksError, setWebhooksError] = useState(null);
  const [newWebhookUrl, setNewWebhookUrl] = useState("");
  const [newWebhookEvents, setNewWebhookEvents] = useState([]);
  const [rules, setRules] = useState([]);
  const [rulesError, setRulesError] = useState(null);
  const [newRuleName, setNewRuleName] = useState("");
  const [newRuleTrigger, setNewRuleTrigger] = useState("");
  const [newRuleFolderId, setNewRuleFolderId] = useState("");
  const [newRuleActionType, setNewRuleActionType] = useState("prompt");
  const [newRulePrompt, setNewRulePrompt] = useState("");
  const [newRuleMode, setNewRuleMode] = useState("chat");
  const [newRuleWebhookUrl, setNewRuleWebhookUrl] = useState("");
  const [mcpServers, setMcpServers] = useState([]);
  const [mcpError, setMcpError] = useState(null);
  const [newMcpName, setNewMcpName] = useState("");
  const [newMcpCommand, setNewMcpCommand] = useState("");
  const [newMcpArgs, setNewMcpArgs] = useState("");
  const [mcpToolsChecking, setMcpToolsChecking] = useState(null);
  const [mcpToolsResult, setMcpToolsResult] = useState({});
  const [newMemory, setNewMemory] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [checkCommand, setCheckCommand] = useState("");
  const [importing, setImporting] = useState(false);
  const [importStatus, setImportStatus] = useState("");
  const [lockEnabled, setLockEnabled] = useState(false);
  const [lockInput, setLockInput] = useState("");
  const [lockMsg, setLockMsg] = useState("");
  const [pullName, setPullName] = useState("");
  const [pullBusy, setPullBusy] = useState(false);
  const [pullStatus, setPullStatus] = useState("");
  const [pullPct, setPullPct] = useState(null);
  const [createForm, setCreateForm] = useState({ name: "", from: "", system: "", adapter: "" });
  const [createBusy, setCreateBusy] = useState(false);
  const [createStatus, setCreateStatus] = useState("");
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
    api.listMemoryConflicts().then(setMemoryConflicts).catch(() => {});
  };

  const reviewMemoryConflicts = async () => {
    setReviewingConflicts(true);
    try {
      await api.reviewMemoryConflicts();
      const conflicts = await api.listMemoryConflicts();
      setMemoryConflicts(conflicts);
    } catch (err) {
      setMemoriesError(err.message);
    } finally {
      setReviewingConflicts(false);
    }
  };

  const resolveMemoryConflict = async (id) => {
    setMemoryConflicts((cs) => cs.filter((c) => c.id !== id));
    await api.resolveMemoryConflict(id);
  };

  const refreshSkills = () => {
    api
      .listSkills()
      .then((s) => {
        setSkills(s);
        setSkillsError(null);
      })
      .catch((err) => setSkillsError(err.message));
  };

  const refreshHardware = () => {
    api.hardwareReport().then(setHardware).catch(() => {});
  };

  const refreshModels = () => {
    api
      .listModels()
      .then((m) => {
        setModels(m);
        setModelsError(null);
      })
      .catch((err) => setModelsError(err.message));
    api.getRoutingStatus().then(setRoutingStatus).catch(() => {});
    api
      .getRoutingOverrideSummary()
      .then((r) => setOverrideSummary(r.overrides || []))
      .catch(() => {});
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
      setCheckCommand(c.agent_check_command || "");
      setEmailForm({
        email_imap_host: c.email_imap_host || "", email_imap_port: c.email_imap_port || 993,
        email_smtp_host: c.email_smtp_host || "", email_smtp_port: c.email_smtp_port || 587,
        email_username: c.email_username || "", email_password: c.email_password || "",
      });
      if (c.email_enabled) refreshEmailInbox();
    });
    api.lockStatus().then(({ enabled }) => setLockEnabled(enabled)).catch(() => {});
    refreshModels();
    refreshMemories();
    refreshSkills();
    refreshHardware();
    refreshPersonas();
    refreshFolders();
    refreshSchedules();
    refreshMcpServers();
    refreshAutomation();
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

  const refreshAutomation = () => {
    api.getAutomationEventTypes().then((types) => {
      setEventTypes(types);
      if (!newRuleTrigger && types.length) setNewRuleTrigger(types[0]);
    }).catch(() => {});
    api.listWebhooks().then((w) => { setWebhooks(w); setWebhooksError(null); }).catch((err) => setWebhooksError(err.message));
    api.listAutomationRules().then((r) => { setRules(r); setRulesError(null); }).catch((err) => setRulesError(err.message));
  };

  const addWebhook = async () => {
    if (!newWebhookUrl.trim() || newWebhookEvents.length === 0) return;
    try {
      await api.createWebhook(newWebhookUrl.trim(), newWebhookEvents);
      setNewWebhookUrl("");
      setNewWebhookEvents([]);
      refreshAutomation();
    } catch (err) {
      setWebhooksError(err.message);
    }
  };

  const toggleWebhook = async (id, enabled) => {
    setWebhooks((ws) => ws.map((w) => (w.id === id ? { ...w, enabled } : w)));
    await api.toggleWebhook(id, enabled);
  };

  const deleteWebhook = async (id) => {
    await api.deleteWebhook(id);
    refreshAutomation();
  };

  const addRule = async () => {
    if (!newRuleName.trim() || !newRuleTrigger) return;
    const actionConfig =
      newRuleActionType === "prompt"
        ? { prompt: newRulePrompt.trim(), mode: newRuleMode }
        : { url: newRuleWebhookUrl.trim() };
    if (newRuleActionType === "prompt" && !actionConfig.prompt) return;
    if (newRuleActionType === "webhook" && !actionConfig.url) return;
    try {
      await api.createAutomationRule({
        name: newRuleName.trim(),
        trigger_type: newRuleTrigger,
        trigger_config: newRuleTrigger === "folder_file_added" && newRuleFolderId.trim() ? { folder_id: newRuleFolderId.trim() } : {},
        action_type: newRuleActionType,
        action_config: actionConfig,
      });
      setNewRuleName("");
      setNewRulePrompt("");
      setNewRuleWebhookUrl("");
      setNewRuleFolderId("");
      refreshAutomation();
    } catch (err) {
      setRulesError(err.message);
    }
  };

  const toggleRule = async (id, enabled) => {
    setRules((rs) => rs.map((r) => (r.id === id ? { ...r, enabled } : r)));
    await api.toggleAutomationRule(id, enabled);
  };

  const deleteRule = async (id) => {
    await api.deleteAutomationRule(id);
    refreshAutomation();
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

  const toggleNtfyEnabled = async (checked) => {
    const updated = await api.patchConfig({ notify_ntfy_enabled: checked });
    setConfig(updated);
  };

  const saveNtfyConfig = async (fields) => {
    const updated = await api.patchConfig(fields);
    setConfig(updated);
  };

  const toggleWakeWordEnabled = async (checked) => {
    const updated = await api.patchConfig({ wake_word_enabled: checked });
    setConfig(updated);
  };

  const saveWakeWordPhrase = async (phrase) => {
    const updated = await api.patchConfig({ wake_word_phrase: phrase });
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

  const saveCheckCommand = async (command) => {
    const updated = await api.patchConfig({ agent_check_command: command });
    setConfig(updated);
  };

  const startPairing = async () => {
    const { code, expires_at } = await api.syncPairStart();
    setPairCode(code);
    setPairExpiresIn(Math.round(expires_at - Date.now() / 1000));
  };

  const joinWithCode = async () => {
    if (!joinHost.trim() || !joinCode.trim()) return;
    setSyncBusy(true);
    setSyncStatus(null);
    try {
      const { encrypted_secret } = await api.syncPairBundle(joinHost.trim().replace(/\/$/, ""), joinCode.trim());
      await api.syncPairComplete(joinCode.trim(), encrypted_secret);
      setSyncStatus({ ok: true, message: "Paired — this device now shares the sync secret." });
      setJoinCode("");
    } catch (err) {
      setSyncStatus({ ok: false, message: err.message });
    } finally {
      setSyncBusy(false);
    }
  };

  const exportSnapshot = async () => {
    if (!syncPassphrase.trim()) return;
    setSyncBusy(true);
    try {
      const { blob } = await api.syncExport(syncPassphrase.trim());
      const file = new Blob([blob], { type: "text/plain" });
      const url = URL.createObjectURL(file);
      const a = document.createElement("a");
      a.href = url;
      a.download = "zenith-sync.blob";
      a.click();
      URL.revokeObjectURL(url);
      setSyncStatus({ ok: true, message: "Exported. Move this file to the other device and import it there." });
    } catch (err) {
      setSyncStatus({ ok: false, message: err.message });
    } finally {
      setSyncBusy(false);
    }
  };

  const importSnapshot = async () => {
    if (!syncPassphrase.trim() || !importBlobText.trim()) return;
    setSyncBusy(true);
    try {
      const { counts } = await api.syncImport(syncPassphrase.trim(), importBlobText.trim());
      const total = Object.values(counts).reduce((a, b) => a + b, 0);
      setSyncStatus({ ok: true, message: `Imported ${total} new item(s) across ${Object.keys(counts).length} tables.` });
      setImportBlobText("");
    } catch (err) {
      setSyncStatus({ ok: false, message: err.message });
    } finally {
      setSyncBusy(false);
    }
  };

  const refreshEmailInbox = () => {
    api.emailMessages().then((m) => {
      setEmailMessages(m);
      setEmailMessagesError(null);
    }).catch((err) => setEmailMessagesError(err.message));
  };

  const saveEmailConfig = async (enable) => {
    const updated = await api.patchConfig({ ...emailForm, email_enabled: enable });
    setConfig(updated);
    if (enable) refreshEmailInbox();
  };

  const testEmailConnection = async () => {
    setEmailTesting(true);
    setEmailTestStatus(null);
    try {
      await saveEmailConfig(true);
      await api.emailTest();
      setEmailTestStatus({ ok: true, message: "Connected." });
      refreshEmailInbox();
    } catch (err) {
      setEmailTestStatus({ ok: false, message: err.message });
    } finally {
      setEmailTesting(false);
    }
  };

  const openEmail = async (id) => {
    setOpenEmailId(id);
    setEmailDetail(null);
    setEmailDraft("");
    try {
      const detail = await api.emailMessage(id);
      setEmailDetail(detail);
    } catch (err) {
      setEmailMessagesError(err.message);
    }
  };

  const summarizeEmail = async (id) => {
    setEmailBusy(true);
    try {
      const { summary } = await api.emailSummarize(id);
      setEmailDetail((d) => ({ ...d, summary }));
    } catch (err) {
      setEmailMessagesError(err.message);
    } finally {
      setEmailBusy(false);
    }
  };

  const draftEmailReply = async (id) => {
    setEmailBusy(true);
    try {
      const result = await api.emailDraftReply(id);
      setEmailDraft(result.draft);
      setEmailResearch(result.research_query ? result : null);
    } catch (err) {
      setEmailMessagesError(err.message);
    } finally {
      setEmailBusy(false);
    }
  };

  const sendEmailReply = async () => {
    if (!emailDetail || !emailDraft.trim()) return;
    setEmailBusy(true);
    try {
      await api.emailSend(emailDetail.from, emailDetail.subject, emailDraft.trim(), emailDetail.id);
      setEmailDraft("");
      setOpenEmailId(null);
    } catch (err) {
      setEmailMessagesError(err.message);
    } finally {
      setEmailBusy(false);
    }
  };

  const handlePull = async (overrideName) => {
    const name = (overrideName || pullName).trim();
    if (!name || pullBusy) return;
    setPullBusy(true);
    setPullStatus("Starting…");
    setPullPct(null);
    await api.pullModel(name, (ev) => {
      if (ev.error) setPullStatus(`Error: ${ev.error}`);
      else if (ev.status === "done") setPullStatus("Done.");
      else {
        setPullStatus(ev.status || "Pulling…");
        if (ev.total && ev.completed) setPullPct(Math.round((ev.completed / ev.total) * 100));
      }
    });
    setPullBusy(false);
    setPullName("");
    setPullPct(null);
    refreshModels();
  };

  const handleCreate = async () => {
    const { name, from } = createForm;
    if (!name.trim() || !from.trim() || createBusy) return;
    setCreateBusy(true);
    setCreateStatus("Creating…");
    await api.createModel(createForm, (ev) => {
      if (ev.error) setCreateStatus(`Error: ${ev.error}`);
      else if (ev.status === "done") setCreateStatus("Created.");
      else setCreateStatus(ev.status || "Working…");
    });
    setCreateBusy(false);
    setCreateForm({ name: "", from: "", system: "", adapter: "" });
    refreshModels();
  };

  const handleDeleteModel = async (name) => {
    if (!window.confirm(`Delete model "${name}"? This removes it from Ollama.`)) return;
    try {
      await api.deleteModel(name);
      refreshModels();
    } catch (err) {
      setModelsError(err.message);
    }
  };

  const handleSetPasscode = async () => {
    const pass = lockInput.trim();
    if (pass.length < 4) {
      setLockMsg("Passcode must be at least 4 characters.");
      return;
    }
    try {
      const { token } = await api.lockSet(pass);
      sessionStorage.setItem("zenith-unlock", token || ""); // stay unlocked in this tab
      setLockEnabled(true);
      setLockInput("");
      setLockMsg("Passcode set. It'll be required next time this tab is opened.");
    } catch (err) {
      setLockMsg(err.message || "Couldn't set passcode.");
    }
  };

  const handleDisablePasscode = async () => {
    const pass = lockInput.trim();
    if (!pass) {
      setLockMsg("Enter your current passcode to turn the lock off.");
      return;
    }
    try {
      await api.lockDisable(pass);
      sessionStorage.removeItem("zenith-unlock");
      setLockEnabled(false);
      setLockInput("");
      setLockMsg("Lock disabled.");
    } catch (err) {
      setLockMsg(err.message || "Couldn't disable the lock.");
    }
  };

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setImporting(true);
    setImportStatus("");
    try {
      const res = await api.importHistory(file);
      const extra = [];
      if (res.memories) extra.push(`${res.memories} memories`);
      if (res.personas) extra.push(`${res.personas} personas`);
      if (res.projects) extra.push(`${res.projects} projects`);
      if (res.quick_actions) extra.push(`${res.quick_actions} quick actions`);
      if (res.folders) extra.push(`${res.folders} watched folders`);
      setImportStatus(
        `Imported ${res.conversations} conversation(s), ${res.messages} messages` +
          (extra.length ? `, ${extra.join(", ")}.` : ".")
      );
      onImported?.();
    } catch (err) {
      setImportStatus(err.message || "Import failed.");
    } finally {
      setImporting(false);
    }
  };

  const toggleAutoCheck = async (checked) => {
    const updated = await api.patchConfig({ agent_auto_check: checked });
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
    if (!window.confirm("Forget everything Zenith has learned about you? This can't be undone."))
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
        aria-modal="true"
        aria-label="Settings"
      >
        <div className="settings-header">
          <div className="settings-title">
            <span className="settings-title-mark" aria-hidden="true" />
            <div>
              <h2>Settings</h2>
              <p className="settings-subtitle">Tune how Zenith runs on your machine</p>
            </div>
          </div>
          <button className="icon-btn settings-close" onClick={onClose} title="Close (Esc)" aria-label="Close">
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
                  <Icon name={s.icon} size={15} />
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
                  Zenith adapts to your environment. Switch themes any time — your choice is
                  remembered on this device.
                </p>

                <div className="setting-row setting-row-stack">
                  <div className="setting-meta">
                    <span className="setting-label">Theme</span>
                    <span className="setting-hint">
                      Eight full re-skins — colors, fonts, shapes, shadows — not just a
                      light/dark toggle.
                    </span>
                  </div>
                  <div className="theme-grid">
                    {THEMES.map((t) => (
                      <button
                        key={t.id}
                        className={`theme-card ${theme === t.id ? "is-selected" : ""}`}
                        onClick={() => onThemeChange(t.id)}
                        aria-pressed={theme === t.id}
                        style={{ background: t.bg, color: t.fg, fontFamily: t.font }}
                      >
                        <span className="theme-card-swatches">
                          <span style={{ background: t.accent }} />
                        </span>
                        <span className="theme-card-label">{t.name}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {THEME_ANIMATIONS[theme]?.length > 0 && (
                  <div className="setting-row">
                    <div className="setting-meta">
                      <span className="setting-label">Ambient background</span>
                      <span className="setting-hint">
                        A subtle animated layer behind the chat. Off by default; only shown
                        for animations that fit this theme.
                      </span>
                    </div>
                    <select
                      className="settings-input"
                      value={ambientAnim}
                      onChange={(e) => onAmbientChange(e.target.value)}
                      aria-label="Ambient background"
                    >
                      <option value="none">None</option>
                      {ANIMATIONS.filter((a) => THEME_ANIMATIONS[theme].includes(a.id)).map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Speak replies aloud</span>
                    <span className="setting-hint">
                      When on, Zenith reads assistant responses using your chosen voice engine.
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

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Message density</span>
                    <span className="setting-hint">
                      Compact fits more on screen — tighter spacing, smaller type.
                    </span>
                  </div>
                  <div className="theme-choice">
                    {["comfortable", "compact"].map((d) => (
                      <button
                        key={d}
                        className={`theme-choice-btn ${density === d ? "is-selected" : ""}`}
                        onClick={() => onDensityChange(d)}
                        aria-pressed={density === d}
                      >
                        <span className="theme-choice-label">
                          {d === "comfortable" ? "Comfortable" : "Compact"}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Desktop notifications</span>
                    <span className="setting-hint">
                      Get a system notification when a response finishes while this tab is in the
                      background, or when a scheduled task runs. Asks the browser for permission.
                    </span>
                  </div>
                  <button
                    className={`switch ${notificationsEnabled ? "switch-on" : ""}`}
                    onClick={() => onNotificationsChange(!notificationsEnabled)}
                    role="switch"
                    aria-checked={!!notificationsEnabled}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Push notifications (ntfy)</span>
                    <span className="setting-hint">
                      Get schedule/digest/urgent-email alerts on your phone via{" "}
                      <a href="https://ntfy.sh" target="_blank" rel="noreferrer">ntfy.sh</a> (or your
                      own self-hosted instance) even while Zenith isn't open. Off by default — this is
                      a deliberate exception to "nothing leaves your machine": once on, a short
                      notification text is sent to the ntfy server you configure below.
                    </span>
                  </div>
                  <button
                    className={`switch ${config?.notify_ntfy_enabled ? "switch-on" : ""}`}
                    onClick={() => toggleNtfyEnabled(!config?.notify_ntfy_enabled)}
                    role="switch"
                    aria-checked={!!config?.notify_ntfy_enabled}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>
                {config?.notify_ntfy_enabled && (
                  <div className="setting-row setting-row-stack">
                    <input
                      className="settings-input"
                      placeholder="ntfy server URL (default https://ntfy.sh)"
                      defaultValue={config?.notify_ntfy_url || ""}
                      aria-label="ntfy server URL"
                      onBlur={(e) => saveNtfyConfig({ notify_ntfy_url: e.target.value.trim() || "https://ntfy.sh" })}
                    />
                    <input
                      className="settings-input"
                      placeholder="Topic (a private, hard-to-guess name — anyone who knows it can read your notifications)"
                      defaultValue={config?.notify_ntfy_topic || ""}
                      aria-label="ntfy topic"
                      onBlur={(e) => saveNtfyConfig({ notify_ntfy_topic: e.target.value.trim() })}
                    />
                    <div className="setting-hint">
                      Events that push a notification:
                      {["digest_generated", "schedule_completed", "urgent_email", "memory_conflict_found", "folder_file_added"].map((ev) => {
                        const active = (config?.notify_event_types || []).includes(ev);
                        return (
                          <button
                            key={ev}
                            className={`theme-choice-btn ${active ? "is-selected" : ""}`}
                            style={{ marginLeft: "0.4rem", marginTop: "0.4rem" }}
                            onClick={() => {
                              const current = config?.notify_event_types || [];
                              const next = active ? current.filter((e) => e !== ev) : [...current, ev];
                              saveNtfyConfig({ notify_event_types: next });
                            }}
                          >
                            {ev.replace(/_/g, " ")}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Wake word</span>
                    <span className="setting-hint">
                      Say a phrase to start talking hands-free, instead of holding the mic button.
                      Off by default — turning this on means Zenith listens to the microphone
                      continuously in the background (short local voice-activity bursts only, nothing
                      is stored beyond the normal transcribe call). A "listening" badge shows
                      whenever this is actually on.
                    </span>
                  </div>
                  <button
                    className={`switch ${config?.wake_word_enabled ? "switch-on" : ""}`}
                    onClick={() => toggleWakeWordEnabled(!config?.wake_word_enabled)}
                    role="switch"
                    aria-checked={!!config?.wake_word_enabled}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>
                {config?.wake_word_enabled && (
                  <div className="setting-row">
                    <div className="setting-meta">
                      <span className="setting-label">Wake phrase</span>
                    </div>
                    <input
                      className="settings-input"
                      defaultValue={config?.wake_word_phrase || "hey zenith"}
                      aria-label="Wake phrase"
                      onBlur={(e) => saveWakeWordPhrase(e.target.value.trim() || "hey zenith")}
                    />
                  </div>
                )}
              </section>
            )}

            {activeSection === "accessibility" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Accessibility</h3>
                <p className="settings-section-desc">
                  These apply everywhere in Zenith, on top of whichever theme you've picked, and
                  are remembered on this device.
                </p>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Text size</span>
                    <span className="setting-hint">Scales all text in the app, not just chat messages.</span>
                  </div>
                  <div className="theme-choice">
                    {[
                      { id: "0.875", label: "Small" },
                      { id: "1", label: "Default" },
                      { id: "1.15", label: "Large" },
                      { id: "1.35", label: "X-Large" },
                    ].map((o) => (
                      <button
                        key={o.id}
                        className={`theme-choice-btn ${fontScale === o.id ? "is-selected" : ""}`}
                        onClick={() => onFontScaleChange(o.id)}
                        aria-pressed={fontScale === o.id}
                      >
                        {o.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">High contrast</span>
                    <span className="setting-hint">
                      Stronger text/background separation and bolder borders, for low-vision or
                      bright-environment use.
                    </span>
                  </div>
                  <button
                    className={`switch ${highContrast ? "switch-on" : ""}`}
                    onClick={() => onHighContrastChange(!highContrast)}
                    role="switch"
                    aria-checked={!!highContrast}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Reduce motion</span>
                    <span className="setting-hint">
                      Turns off transitions, ambient backgrounds, and animated UI regardless of
                      your OS setting.
                    </span>
                  </div>
                  <button
                    className={`switch ${reduceMotion ? "switch-on" : ""}`}
                    onClick={() => onReduceMotionChange(!reduceMotion)}
                    role="switch"
                    aria-checked={!!reduceMotion}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Dyslexia-friendly font</span>
                    <span className="setting-hint">
                      Switches body text to a font with wider letter spacing and looser line height.
                    </span>
                  </div>
                  <button
                    className={`switch ${dyslexiaFont ? "switch-on" : ""}`}
                    onClick={() => onDyslexiaFontChange(!dyslexiaFont)}
                    role="switch"
                    aria-checked={!!dyslexiaFont}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Always underline links</span>
                    <span className="setting-hint">
                      Helps distinguish links from regular text without relying on color alone.
                    </span>
                  </div>
                  <button
                    className={`switch ${underlineLinks ? "switch-on" : ""}`}
                    onClick={() => onUnderlineLinksChange(!underlineLinks)}
                    role="switch"
                    aria-checked={!!underlineLinks}
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
                  Zenith talks to a local Ollama instance. Point it at the host it's running on.
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

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  Image generation
                </h3>
                <p className="settings-section-desc">
                  Optional. Point this at a local Stable Diffusion server with its API enabled
                  (AUTOMATIC1111 / Forge / SD.Next started with <code>--api</code>). Once set, an{" "}
                  <strong>Image</strong> mode appears in the composer. Leave blank to keep it off.
                </p>
                <div className="settings-row">
                  <input
                    className="settings-input"
                    placeholder="http://localhost:7860"
                    aria-label="Image generation server URL"
                    defaultValue={config?.image_gen_url || ""}
                    onBlur={async (e) => {
                      const updated = await api.patchConfig({ image_gen_url: e.target.value.trim() });
                      setConfig(updated);
                    }}
                  />
                </div>

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  Multi-device access
                </h3>
                <p className="settings-section-desc">
                  Let other devices on your network (or Tailscale) reach Zenith — open it from a
                  phone at <code>http://&lt;this-machine-ip&gt;:5173</code>. Widens who can reach the
                  API, so pair it with the passcode lock. Takes effect after a backend restart. See
                  MULTIDEVICE.md.
                </p>
                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Allow LAN / Tailscale access</span>
                    <span className="setting-hint">
                      Accepts requests from private-network and <code>*.ts.net</code> origins.
                    </span>
                  </div>
                  <button
                    className={`switch ${config?.cors_allow_lan ? "switch-on" : ""}`}
                    onClick={async () => {
                      const updated = await api.patchConfig({ cors_allow_lan: !config?.cors_allow_lan });
                      setConfig(updated);
                    }}
                    role="switch"
                    aria-checked={!!config?.cors_allow_lan}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>
              </section>
            )}

            {activeSection === "memory" && (
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
            )}

            {activeSection === "skills" && (
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
            )}

            {activeSection === "email" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Email</h3>
                <p className="settings-section-desc">
                  Connect your own IMAP/SMTP account — no third-party mail API. Credentials are
                  stored the same way as other local settings (plaintext in Zenith's own config
                  file, not encrypted at rest — use an app password if your provider supports
                  one). Summaries and reply drafts run on your local model; nothing sends until
                  you review and hit send.
                </p>
                <div className="settings-row">
                  <input
                    className="settings-input"
                    placeholder="IMAP host (e.g. imap.gmail.com)"
                    aria-label="IMAP host"
                    value={emailForm.email_imap_host}
                    onChange={(e) => setEmailForm((f) => ({ ...f, email_imap_host: e.target.value }))}
                  />
                  <input
                    className="settings-input"
                    style={{ maxWidth: "90px" }}
                    placeholder="Port"
                    aria-label="IMAP port"
                    type="number"
                    value={emailForm.email_imap_port}
                    onChange={(e) => setEmailForm((f) => ({ ...f, email_imap_port: Number(e.target.value) }))}
                  />
                </div>
                <div className="settings-row" style={{ marginTop: "0.5rem" }}>
                  <input
                    className="settings-input"
                    placeholder="SMTP host (e.g. smtp.gmail.com)"
                    aria-label="SMTP host"
                    value={emailForm.email_smtp_host}
                    onChange={(e) => setEmailForm((f) => ({ ...f, email_smtp_host: e.target.value }))}
                  />
                  <input
                    className="settings-input"
                    style={{ maxWidth: "90px" }}
                    placeholder="Port"
                    aria-label="SMTP port"
                    type="number"
                    value={emailForm.email_smtp_port}
                    onChange={(e) => setEmailForm((f) => ({ ...f, email_smtp_port: Number(e.target.value) }))}
                  />
                </div>
                <div className="settings-row" style={{ marginTop: "0.5rem" }}>
                  <input
                    className="settings-input"
                    placeholder="Email address"
                    aria-label="Email address"
                    value={emailForm.email_username}
                    onChange={(e) => setEmailForm((f) => ({ ...f, email_username: e.target.value }))}
                  />
                  <input
                    className="settings-input"
                    placeholder="App password"
                    aria-label="App password"
                    type="password"
                    value={emailForm.email_password}
                    onChange={(e) => setEmailForm((f) => ({ ...f, email_password: e.target.value }))}
                  />
                </div>
                <div className="settings-row" style={{ marginTop: "0.75rem" }}>
                  <button className="settings-btn-primary" onClick={testEmailConnection} disabled={emailTesting}>
                    {emailTesting ? "Testing…" : "Save & test connection"}
                  </button>
                  {config?.email_enabled && (
                    <button className="text-btn" onClick={() => saveEmailConfig(false)}>
                      Disconnect
                    </button>
                  )}
                </div>
                {emailTestStatus && (
                  <p className={emailTestStatus.ok ? "setting-hint" : "settings-error"}>
                    {emailTestStatus.message}
                  </p>
                )}

                {config?.email_enabled && (
                  <>
                    <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                      Inbox
                    </h3>
                    {emailMessagesError && <p className="settings-error">{emailMessagesError}</p>}
                    <button className="text-btn" onClick={refreshEmailInbox} style={{ marginBottom: "0.5rem" }}>
                      Refresh
                    </button>
                    <ul className="model-list">
                      {emailMessages.map((m) => (
                        <li key={m.id} style={{ display: "block" }}>
                          <div
                            className="settings-row"
                            style={{ cursor: "pointer", justifyContent: "space-between" }}
                            onClick={() => openEmail(openEmailId === m.id ? null : m.id)}
                          >
                            <span className="model-name" style={{ flex: 1 }}>
                              {m.subject || "(no subject)"}
                              <span style={{ display: "block", fontSize: "0.75em", color: "var(--text-tertiary)" }}>
                                {m.from} — {m.snippet}
                              </span>
                            </span>
                          </div>
                          {openEmailId === m.id && emailDetail && (
                            <div style={{ padding: "0.5rem 0" }}>
                              <pre className="plan-card-body">{emailDetail.body}</pre>
                              <div className="settings-row">
                                <button className="text-btn" onClick={() => summarizeEmail(m.id)} disabled={emailBusy}>
                                  Summarize
                                </button>
                                <button className="text-btn" onClick={() => draftEmailReply(m.id)} disabled={emailBusy}>
                                  Draft reply
                                </button>
                              </div>
                              {emailDetail.summary && <p className="setting-hint">{emailDetail.summary}</p>}
                              {emailResearch && (
                                <p className="setting-hint">
                                  Researched "{emailResearch.research_query}" before drafting
                                  {emailResearch.research_sources?.length > 0 &&
                                    ` — ${emailResearch.research_sources.length} source(s) used.`}
                                </p>
                              )}
                              {emailDraft && (
                                <>
                                  <textarea
                                    className="settings-input"
                                    style={{ width: "100%", minHeight: "100px", marginTop: "0.5rem" }}
                                    aria-label="Reply draft"
                                    value={emailDraft}
                                    onChange={(e) => setEmailDraft(e.target.value)}
                                  />
                                  <button
                                    className="settings-btn-primary"
                                    style={{ marginTop: "0.5rem" }}
                                    onClick={sendEmailReply}
                                    disabled={emailBusy}
                                  >
                                    Send
                                  </button>
                                </>
                              )}
                            </div>
                          )}
                        </li>
                      ))}
                      {emailMessages.length === 0 && !emailMessagesError && (
                        <li className="model-empty">No messages loaded yet.</li>
                      )}
                    </ul>
                  </>
                )}
              </section>
            )}

            {activeSection === "sync" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Sync</h3>
                <p className="settings-section-desc">
                  Multi-device sync is deliberately two-factor: a passphrase you choose
                  <em> and</em> a sync secret that only ever moves between devices through a
                  short-lived, single-use pairing code — never sent in plaintext, never stored
                  anywhere but on your devices. Knowing the passphrase alone doesn't decrypt
                  anything on an unpaired device. This syncs Notes, To-dos, Calendar, Personas,
                  Projects, and Memories — not full chat history.
                </p>

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  1. Pair a new device
                </h3>
                <p className="settings-section-desc">
                  On the device you already trust, generate a code. On the new device, enter
                  that code plus this trusted device's address (both must be reachable on the
                  same network — LAN or Tailscale).
                </p>
                <div className="settings-row">
                  <button className="settings-btn-primary" onClick={startPairing}>
                    Generate pairing code
                  </button>
                  {pairCode && (
                    <span className="setting-hint">
                      Code: <strong>{pairCode}</strong> (valid {pairExpiresIn}s — enter this on the
                      new device)
                    </span>
                  )}
                </div>

                <div className="settings-row" style={{ marginTop: "0.75rem" }}>
                  <input
                    className="settings-input"
                    placeholder="Trusted device address, e.g. http://192.168.1.20:8420"
                    aria-label="Trusted device address"
                    value={joinHost}
                    onChange={(e) => setJoinHost(e.target.value)}
                  />
                  <input
                    className="settings-input"
                    placeholder="Pairing code"
                    aria-label="Pairing code"
                    value={joinCode}
                    onChange={(e) => setJoinCode(e.target.value)}
                  />
                  <button className="settings-btn-primary" onClick={joinWithCode} disabled={syncBusy}>
                    {syncBusy ? "…" : "Join"}
                  </button>
                </div>

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  2. Sync a snapshot
                </h3>
                <p className="settings-section-desc">
                  Once paired, export an encrypted snapshot on one device and import it on the
                  other. Manual and on-demand — not continuous background sync.
                </p>
                <div className="settings-row">
                  <input
                    className="settings-input"
                    type="password"
                    placeholder="Sync passphrase (same on both devices)"
                    aria-label="Sync passphrase"
                    value={syncPassphrase}
                    onChange={(e) => setSyncPassphrase(e.target.value)}
                  />
                </div>
                <div className="settings-row" style={{ marginTop: "0.5rem" }}>
                  <button className="settings-btn-primary" onClick={exportSnapshot} disabled={syncBusy}>
                    Export snapshot
                  </button>
                </div>
                <div className="settings-row" style={{ marginTop: "0.5rem" }}>
                  <textarea
                    className="settings-input"
                    style={{ width: "100%", minHeight: "70px" }}
                    placeholder="Paste an exported snapshot's contents here to import…"
                    aria-label="Snapshot to import"
                    value={importBlobText}
                    onChange={(e) => setImportBlobText(e.target.value)}
                  />
                </div>
                <div className="settings-row" style={{ marginTop: "0.5rem" }}>
                  <button className="settings-btn-primary" onClick={importSnapshot} disabled={syncBusy}>
                    Import snapshot
                  </button>
                </div>
                {syncStatus && (
                  <p className={syncStatus.ok ? "setting-hint" : "settings-error"} style={{ marginTop: "0.5rem" }}>
                    {syncStatus.message}
                  </p>
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
            )}

            {activeSection === "agent" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Agent tools</h3>
                <p className="settings-section-desc">
                  Off by default. When on, Zenith can run shell commands and read/write files
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
                      Master switch. Off = the Agent composer toggle does nothing.
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
                    <option value="plan">Plan-first — approve a plan, then it runs unattended</option>
                  </select>
                  <span className="setting-hint">
                    {config?.agent_mode === "full"
                      ? "Nothing pauses for approval. Only as safe as your prompts."
                      : config?.agent_mode === "semi"
                      ? "Read-only calls (read/list/search) run immediately; writes and shell commands with side effects still ask first."
                      : config?.agent_mode === "plan"
                      ? "Zenith drafts a step-by-step plan and waits for your approval; once approved, it executes the whole plan without pausing at each step."
                      : "Every tool call — even a plain file read — shows up in chat for you to approve or deny."}
                  </span>
                </div>

                <p className="settings-hint-note">
                  Small models (roughly under ~4B parameters) often skip the tool-calling
                  protocol entirely and answer from guesswork instead of actually using a tool —
                  this isn't a bug in Zenith, it's a real limitation of small local models. Pin
                  the "general" role to a larger model in Model routing for agent turns to work
                  reliably.
                </p>

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  Test / lint checks
                </h3>
                <p className="settings-section-desc">
                  A command the agent can run to verify its own edits — e.g.{" "}
                  <code>pytest -q</code> or <code>npm test</code>. It runs in the conversation's
                  working directory. The agent can call it any time via its <code>run_checks</code>{" "}
                  tool; turn on auto-check to have it run automatically after every file edit.
                </p>
                <div className="settings-row">
                  <input
                    className="settings-input"
                    placeholder="e.g. pytest -q"
                    aria-label="Check command"
                    value={checkCommand}
                    onChange={(e) => setCheckCommand(e.target.value)}
                    onBlur={(e) => saveCheckCommand(e.target.value.trim())}
                  />
                </div>
                <div className="setting-row" style={{ marginTop: "0.75rem" }}>
                  <div>
                    <strong>Auto-run after edits</strong>
                    <span className="setting-hint">
                      After each successful file edit, run the check command and feed the pass/fail
                      back to the agent so it fixes breakage on its own.
                    </span>
                  </div>
                  <button
                    className={`switch ${config?.agent_auto_check ? "switch-on" : ""}`}
                    onClick={() => toggleAutoCheck(!config?.agent_auto_check)}
                    disabled={!config?.agent_enabled}
                    role="switch"
                    aria-checked={!!config?.agent_auto_check}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  MCP servers
                </h3>
                <p className="settings-section-desc">
                  Connect external MCP (Model Context Protocol) tool servers — email, calendar,
                  Notion, whatever's published — instead of Zenith hand-building each
                  integration. Runs as a local subprocess over stdio, same free-by-construction
                  posture as everything else here. Their tools appear in agent mode's tool list
                  automatically, prefixed <code>mcp__servername__</code>, and go through the same
                  approval gate as bash/write_file (external tools are unknown behavior, so
                  they're always classified risky).
                </p>

                <p className="setting-hint" style={{ marginBottom: "0.4rem" }}>
                  Popular servers (keyless, run locally via npx — click to fill in the form below,
                  then adjust and add):
                </p>
                <div className="mcp-popular-list">
                  {POPULAR_MCP_SERVERS.map((s) => (
                    <button
                      key={s.name}
                      className="mcp-popular-chip"
                      onClick={() => {
                        setNewMcpName(s.name);
                        setNewMcpCommand(s.command);
                        setNewMcpArgs(s.args);
                      }}
                      title={s.description}
                    >
                      {s.name}
                    </button>
                  ))}
                </div>

                <div className="settings-row">
                  <input
                    className="settings-input"
                    placeholder="Name"
                    aria-label="MCP server name"
                    value={newMcpName}
                    onChange={(e) => setNewMcpName(e.target.value)}
                    style={{ flex: "0 0 120px" }}
                  />
                  <input
                    className="settings-input"
                    placeholder="Command, e.g. npx or /path/to/python"
                    aria-label="MCP server command"
                    value={newMcpCommand}
                    onChange={(e) => setNewMcpCommand(e.target.value)}
                  />
                  <input
                    className="settings-input"
                    placeholder="Args (space-separated)"
                    aria-label="MCP server args"
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
                          <button className="icon-btn" onClick={() => removeMcpServer(s.id)} title="Remove" aria-label="Remove server">
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
            )}

            {activeSection === "routing" && (
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
            )}

            {activeSection === "models" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Installed models</h3>
                <p className="settings-section-desc">
                  Everything below is running locally on your Ollama. No data leaves your machine.
                </p>
                {hardware && (
                  <div className="hw-summary">
                    <span>{hardware.hardware.cpu_cores} CPU cores</span>
                    <span>{hardware.hardware.ram_gb ?? "?"} GB RAM</span>
                    <span>
                      {hardware.hardware.gpu
                        ? `${hardware.hardware.gpu.name}${hardware.hardware.gpu.vram_gb ? ` (${hardware.hardware.gpu.vram_gb} GB VRAM)` : ""}`
                        : "No GPU detected — running on CPU"}
                    </span>
                  </div>
                )}
                <ul className="model-list">
                  {models.map((m) => {
                    const hw = hardware?.installed.find((x) => x.name === m.name);
                    return (
                      <li key={m.name}>
                        <span className="model-name">{m.name}</span>
                        <span className="model-roles">
                          {m.roles?.map((r) => (
                            <span key={r} className="role-chip" data-role={r}>
                              {r}
                            </span>
                          ))}
                          {hw && hw.fit !== "unknown" && (
                            <span className={`fit-chip fit-chip-${hw.fit}`} title="Estimated fit for your hardware">
                              {hw.fit === "comfortable" ? "fits well" : hw.fit === "tight" ? "tight fit" : "will struggle"}
                            </span>
                          )}
                          <button
                            className="model-delete-btn"
                            onClick={() => handleDeleteModel(m.name)}
                            title="Delete model from Ollama"
                            aria-label={`Delete model ${m.name} from Ollama`}
                          >
                            <Icon name="x" size={13} />
                          </button>
                        </span>
                      </li>
                    );
                  })}
                  {models.length === 0 && !modelsError && <li className="model-empty">Loading…</li>}
                </ul>

                {hardware?.recommended.length > 0 && (
                  <>
                    <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                      Recommended for your hardware
                    </h3>
                    <p className="settings-section-desc">
                      Sized to what {hardware.budget_gb ? `~${hardware.budget_gb} GB` : "this machine"} can
                      actually run well — best fit first. All run locally on your Ollama.
                    </p>
                    <div
                      role="group"
                      aria-label="Filter recommended models by task"
                      style={{ display: "flex", flexWrap: "wrap", gap: "6px", margin: "8px 0 12px" }}
                    >
                      {MODEL_TASK_FILTERS.map((f) => (
                        <button
                          key={f.key}
                          type="button"
                          onClick={() => setModelTaskFilter(f.key)}
                          aria-pressed={modelTaskFilter === f.key}
                          style={{
                            fontSize: "0.75rem",
                            padding: "4px 10px",
                            borderRadius: "999px",
                            border: "1px solid var(--bg-inset)",
                            background: modelTaskFilter === f.key ? "var(--signal-general, #4a6cf7)" : "var(--bg-panel-raised, transparent)",
                            color: modelTaskFilter === f.key ? "#fff" : "var(--text-secondary)",
                            cursor: "pointer",
                          }}
                        >
                          {f.label}
                        </button>
                      ))}
                    </div>
                    <ul className="model-list">
                      {hardware.recommended
                        .filter((m) => modelTaskFilter === "all" || m.role === modelTaskFilter)
                        .map((m) => (
                        <li key={m.name}>
                          <span className="model-name" style={{ flex: 1 }}>
                            {m.name}
                            <span style={{ display: "block", fontSize: "0.75em", color: "var(--text-tertiary)" }}>
                              {m.note}
                            </span>
                          </span>
                          <span className={`fit-chip fit-chip-${m.fit}`}>
                            {m.fit === "comfortable" ? "fits well" : m.fit === "tight" ? "tight fit" : "will struggle"}
                          </span>
                          <button
                            className="text-btn"
                            onClick={() => {
                              setPullName(m.name);
                              handlePull(m.name);
                            }}
                          >
                            Pull
                          </button>
                        </li>
                      ))}
                    </ul>
                  </>
                )}

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  Cloud model options
                </h3>
                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Show cloud model options</span>
                    <span className="setting-hint">
                      Larger models than your hardware can run, hosted by Ollama, requires an
                      ollama.com account. Nothing else in Zenith calls out to the internet without
                      this being explicitly on.
                    </span>
                  </div>
                  <button
                    className={`switch ${config?.show_cloud_model_suggestions ? "switch-on" : ""}`}
                    onClick={async () =>
                      setConfig(
                        await api.patchConfig({
                          show_cloud_model_suggestions: !config?.show_cloud_model_suggestions,
                        })
                      )
                    }
                    role="switch"
                    aria-checked={!!config?.show_cloud_model_suggestions}
                  >
                    <span className="switch-thumb" />
                  </button>
                </div>

                {config?.show_cloud_model_suggestions && hardware?.cloud_recommended?.length > 0 && (
                  <div
                    style={{
                      marginTop: "8px",
                      padding: "12px",
                      border: "1px dashed color-mix(in srgb, #7c5cff 45%, transparent)",
                      borderRadius: "var(--radius-sm)",
                      background: "color-mix(in srgb, #7c5cff 6%, transparent)",
                    }}
                  >
                    <p className="settings-section-desc">
                      These do <strong>not</strong> run on this machine — they run on Ollama's own
                      servers. Pulling one requires signing into an ollama.com account outside of
                      Zenith; Zenith does not manage that sign-in, it only helps you pick a model.
                    </p>
                    <div
                      role="group"
                      aria-label="Filter cloud models by task"
                      style={{ display: "flex", flexWrap: "wrap", gap: "6px", margin: "8px 0 12px" }}
                    >
                      {MODEL_TASK_FILTERS.map((f) => (
                        <button
                          key={f.key}
                          type="button"
                          onClick={() => setModelTaskFilter(f.key)}
                          aria-pressed={modelTaskFilter === f.key}
                          style={{
                            fontSize: "0.75rem",
                            padding: "4px 10px",
                            borderRadius: "999px",
                            border: "1px solid var(--bg-inset)",
                            background: modelTaskFilter === f.key ? "var(--signal-general, #4a6cf7)" : "var(--bg-panel-raised, transparent)",
                            color: modelTaskFilter === f.key ? "#fff" : "var(--text-secondary)",
                            cursor: "pointer",
                          }}
                        >
                          {f.label}
                        </button>
                      ))}
                    </div>
                    <ul className="model-list">
                      {hardware.cloud_recommended
                        .filter((m) => modelTaskFilter === "all" || m.role === modelTaskFilter)
                        .map((m) => (
                        <li key={m.name}>
                          <span className="model-name" style={{ flex: 1 }}>
                            {m.name}
                            <span style={{ display: "block", fontSize: "0.75em", color: "var(--text-tertiary)" }}>
                              {m.note}
                            </span>
                          </span>
                          <span
                            title="Runs on Ollama's servers, not this machine"
                            style={{
                              fontSize: "10px",
                              padding: "2px 8px",
                              borderRadius: "999px",
                              textTransform: "uppercase",
                              letterSpacing: "0.03em",
                              whiteSpace: "nowrap",
                              background: "color-mix(in srgb, #7c5cff 22%, transparent)",
                              color: "#7c5cff",
                              fontWeight: 600,
                            }}
                          >
                            Cloud
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  Pull a model
                </h3>
                <p className="settings-section-desc">
                  Download a model from the Ollama registry — no CLI needed. Try{" "}
                  <code>llama3.2</code>, <code>qwen2.5-coder</code>, or <code>llava</code>.
                </p>
                <div className="settings-row">
                  <input
                    className="settings-input"
                    placeholder="model name, e.g. llama3.2:3b"
                    aria-label="Model name to pull"
                    value={pullName}
                    onChange={(e) => setPullName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handlePull()}
                    disabled={pullBusy}
                  />
                  <button className="settings-btn-primary" onClick={() => handlePull()} disabled={pullBusy || !pullName.trim()}>
                    {pullBusy ? "Pulling…" : "Pull"}
                  </button>
                </div>
                {pullStatus && (
                  <div className="model-progress">
                    <span className="setting-hint">
                      {pullStatus}
                      {pullPct != null ? ` — ${pullPct}%` : ""}
                    </span>
                    {pullPct != null && (
                      <div className="model-progress-bar">
                        <div className="model-progress-fill" style={{ width: `${pullPct}%` }} />
                      </div>
                    )}
                  </div>
                )}

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  Create a variant / apply an adapter
                </h3>
                <p className="settings-section-desc">
                  Make a new model from an existing one — bake in a system prompt, or apply a
                  fine-tuned LoRA adapter (point <code>adapter</code> at a GGUF adapter file Ollama
                  can read).
                </p>
                <div className="setting-row setting-row-stack" style={{ gap: "0.5rem" }}>
                  <input
                    className="settings-input"
                    placeholder="New model name, e.g. my-assistant"
                    aria-label="New model name"
                    value={createForm.name}
                    onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
                  />
                  <input
                    className="settings-input"
                    placeholder="Base model (from), e.g. llama3.2:3b"
                    aria-label="Base model"
                    value={createForm.from}
                    onChange={(e) => setCreateForm((f) => ({ ...f, from: e.target.value }))}
                  />
                  <input
                    className="settings-input"
                    placeholder="System prompt (optional)"
                    aria-label="System prompt"
                    value={createForm.system}
                    onChange={(e) => setCreateForm((f) => ({ ...f, system: e.target.value }))}
                  />
                  <input
                    className="settings-input"
                    placeholder="Adapter path (optional, for LoRA)"
                    aria-label="Adapter path"
                    value={createForm.adapter}
                    onChange={(e) => setCreateForm((f) => ({ ...f, adapter: e.target.value }))}
                  />
                  <button
                    className="settings-btn-primary"
                    onClick={handleCreate}
                    disabled={createBusy || !createForm.name.trim() || !createForm.from.trim()}
                  >
                    {createBusy ? "Creating…" : "Create"}
                  </button>
                  {createStatus && <span className="setting-hint">{createStatus}</span>}
                </div>
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
                  Everything Zenith knows about you, in a format you can actually read and keep
                  — no lock-in. Downloads run locally against your own backend.
                </p>

                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Export as JSON</span>
                    <span className="setting-hint">
                      Complete, machine-readable — every conversation, message, memory, persona,
                      project, quick action, and watched folder. (Schedules aren't included —
                      they're re-created per-instance from Settings -&gt; Schedules.)
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
                      reading outside Zenith.
                    </span>
                  </div>
                  <a className="settings-btn-primary" href={api.exportUrl("markdown")} download>
                    Download .zip
                  </a>
                </div>

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  Import
                </h3>
                <p className="settings-section-desc">
                  Bring your history over from another tool, or move it between two Zenith
                  instances — upload a ChatGPT/Claude <code>conversations.json</code>, or a
                  <code> zenith-export.json</code> downloaded from "Export as JSON" above (on this
                  machine or another one). A Zenith-to-Zenith import also re-creates projects
                  (conversations are re-linked to the new project), quick actions, and watched
                  folders (skipped if the path doesn't exist on this machine). Zenith detects
                  which kind of file it is automatically.
                </p>
                <div className="setting-row">
                  <div className="setting-meta">
                    <span className="setting-label">Import a file</span>
                    <span className="setting-hint">
                      {importStatus || "Your original messages and timestamps are preserved."}
                    </span>
                  </div>
                  <label className="settings-btn-primary" style={{ cursor: "pointer" }}>
                    {importing ? "Importing…" : "Choose a file"}
                    <input
                      type="file"
                      accept="application/json,.json"
                      hidden
                      disabled={importing}
                      onChange={handleImport}
                    />
                  </label>
                </div>

                <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
                  Passcode lock
                </h3>
                <p className="settings-section-desc">
                  Require a passcode to open Zenith on this machine — useful if others use the same
                  computer. Note: this is a login gate, <strong>not</strong> at-rest encryption; the
                  database file itself is still readable by anyone with filesystem access.
                </p>
                <div className="settings-row">
                  <input
                    className="settings-input"
                    type="password"
                    placeholder={lockEnabled ? "Current passcode (to change/disable)" : "Set a passcode (min 4 chars)"}
                    aria-label={lockEnabled ? "Current passcode" : "Set a passcode"}
                    value={lockInput}
                    onChange={(e) => setLockInput(e.target.value)}
                  />
                  <button className="settings-btn-primary" onClick={handleSetPasscode}>
                    {lockEnabled ? "Change" : "Enable lock"}
                  </button>
                  {lockEnabled && (
                    <button className="settings-btn-secondary" onClick={handleDisablePasscode}>
                      Disable
                    </button>
                  )}
                </div>
                {lockMsg && <span className="setting-hint">{lockMsg}</span>}
              </section>
            )}

            {activeSection === "folders" && (
              <section className="settings-section">
                <h3 className="settings-section-title">Watched folders</h3>
                <p className="settings-section-desc">
                  Point Zenith at a folder and it periodically re-indexes matching files
                  (.md/.txt/.py/.js/.ts/.json) so their content is recalled in chat automatically
                  — no manual upload per file. Paths are resolved on the <em>backend</em>, which
                  in the Docker deployment means the container's own filesystem unless you've
                  added a host bind mount in docker-compose.yml.
                </p>

                <div className="settings-row">
                  <input
                    className="settings-input"
                    placeholder="/path/to/notes"
                    aria-label="Folder path to watch"
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
                        <button className="icon-btn" onClick={() => removeFolder(f.id)} title="Stop watching" aria-label="Stop watching folder">
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
                      aria-label="Schedule name"
                      value={newScheduleName}
                      onChange={(e) => setNewScheduleName(e.target.value)}
                    />
                    <select
                      className="settings-select"
                      style={{ flex: "0 0 140px" }}
                      value={newScheduleMode}
                      onChange={(e) => setNewScheduleMode(e.target.value)}
                      aria-label="Schedule mode"
                    >
                      <option value="chat">Chat</option>
                      <option value="research">Deep Research</option>
                    </select>
                  </div>
                  <textarea
                    className="settings-textarea"
                    rows={2}
                    placeholder="Prompt to run each time…"
                    aria-label="Prompt to run each time"
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
                          <button className="icon-btn" onClick={() => deleteSchedule(s.id)} title="Delete" aria-label="Delete schedule">
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

            {activeSection === "automation" && (
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
            )}

            {activeSection === "about" && (
              <section className="settings-section about-section">
                <img src="/icon-192.png" alt="Zenith" className="about-logo" />
                <h3 className="settings-section-title">Zenith</h3>
                <p className="settings-section-desc">
                  A local-first AI cockpit — chat, agent tools, email, calendar, notes, research,
                  and multi-device sync, all running on your own machine. No cloud, no accounts.
                </p>
                <p className="setting-hint">Version 0.9 · built on Ollama</p>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}