import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import { SECTIONS } from "./settings/constants.js";
import { SettingsContext } from "./settings/SettingsContext.js";
import AppearanceSection from "./settings/AppearanceSection.jsx";
import AccessibilitySection from "./settings/AccessibilitySection.jsx";
import ConnectionSection from "./settings/ConnectionSection.jsx";
import MemorySection from "./settings/MemorySection.jsx";
import SkillsSection from "./settings/SkillsSection.jsx";
import EmailSection from "./settings/EmailSection.jsx";
import SyncSection from "./settings/SyncSection.jsx";
import PersonasSection from "./settings/PersonasSection.jsx";
import AgentSection from "./settings/AgentSection.jsx";
import CouncilSection from "./settings/CouncilSection.jsx";
import RoutingSection from "./settings/RoutingSection.jsx";
import ModelsSection from "./settings/ModelsSection.jsx";
import VoiceSection from "./settings/VoiceSection.jsx";
import DataSection from "./settings/DataSection.jsx";
import FoldersSection from "./settings/FoldersSection.jsx";
import SchedulesSection from "./settings/SchedulesSection.jsx";
import AutomationSection from "./settings/AutomationSection.jsx";
import AboutSection from "./settings/AboutSection.jsx";


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
  // oxlint-disable-next-line react-hooks/exhaustive-deps -- initial load on mount only
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

  const toggleNativeTools = async (checked) => {
    const updated = await api.patchConfig({ agent_native_tools: checked });
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

  const settingsContext = {
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
    initialSection,
    onUseSkill,
    fontScale,
    onFontScaleChange,
    highContrast,
    onHighContrastChange,
    reduceMotion,
    onReduceMotionChange,
    dyslexiaFont,
    onDyslexiaFontChange,
    underlineLinks,
    onUnderlineLinksChange,
    config,
    setConfig,
    models,
    setModels,
    modelsError,
    setModelsError,
    host,
    setHost,
    saving,
    setSaving,
    activeSection,
    setActiveSection,
    memories,
    setMemories,
    memoriesError,
    setMemoriesError,
    memoryConflicts,
    setMemoryConflicts,
    reviewingConflicts,
    setReviewingConflicts,
    skills,
    setSkills,
    skillsError,
    setSkillsError,
    hardware,
    setHardware,
    modelTaskFilter,
    setModelTaskFilter,
    routingStatus,
    setRoutingStatus,
    overrideSummary,
    setOverrideSummary,
    emailForm,
    setEmailForm,
    emailTestStatus,
    setEmailTestStatus,
    emailTesting,
    setEmailTesting,
    emailMessages,
    setEmailMessages,
    emailMessagesError,
    setEmailMessagesError,
    openEmailId,
    setOpenEmailId,
    emailDetail,
    setEmailDetail,
    emailDraft,
    setEmailDraft,
    emailBusy,
    setEmailBusy,
    emailResearch,
    setEmailResearch,
    syncPassphrase,
    setSyncPassphrase,
    pairCode,
    setPairCode,
    pairExpiresIn,
    setPairExpiresIn,
    joinHost,
    setJoinHost,
    joinCode,
    setJoinCode,
    syncStatus,
    setSyncStatus,
    syncBusy,
    setSyncBusy,
    importBlobText,
    setImportBlobText,
    personas,
    setPersonas,
    newPersonaName,
    setNewPersonaName,
    newPersonaIcon,
    setNewPersonaIcon,
    newPersonaPrompt,
    setNewPersonaPrompt,
    personasError,
    setPersonasError,
    folders,
    setFolders,
    foldersError,
    setFoldersError,
    newFolderPath,
    setNewFolderPath,
    scanningFolder,
    setScanningFolder,
    schedules,
    setSchedules,
    schedulesError,
    setSchedulesError,
    newScheduleName,
    setNewScheduleName,
    newSchedulePrompt,
    setNewSchedulePrompt,
    newScheduleMode,
    setNewScheduleMode,
    newScheduleInterval,
    setNewScheduleInterval,
    runningSchedule,
    setRunningSchedule,
    expandedSchedule,
    setExpandedSchedule,
    scheduleRuns,
    setScheduleRuns,
    eventTypes,
    setEventTypes,
    webhooks,
    setWebhooks,
    webhooksError,
    setWebhooksError,
    newWebhookUrl,
    setNewWebhookUrl,
    newWebhookEvents,
    setNewWebhookEvents,
    rules,
    setRules,
    rulesError,
    setRulesError,
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
    mcpServers,
    setMcpServers,
    mcpError,
    setMcpError,
    newMcpName,
    setNewMcpName,
    newMcpCommand,
    setNewMcpCommand,
    newMcpArgs,
    setNewMcpArgs,
    mcpToolsChecking,
    setMcpToolsChecking,
    mcpToolsResult,
    setMcpToolsResult,
    newMemory,
    setNewMemory,
    systemPrompt,
    setSystemPrompt,
    checkCommand,
    setCheckCommand,
    importing,
    setImporting,
    importStatus,
    setImportStatus,
    lockEnabled,
    setLockEnabled,
    lockInput,
    setLockInput,
    lockMsg,
    setLockMsg,
    pullName,
    setPullName,
    pullBusy,
    setPullBusy,
    pullStatus,
    setPullStatus,
    pullPct,
    setPullPct,
    createForm,
    setCreateForm,
    createBusy,
    setCreateBusy,
    createStatus,
    setCreateStatus,
    promptSaving,
    setPromptSaving,
    promptSaved,
    setPromptSaved,
    refreshMemories,
    reviewMemoryConflicts,
    resolveMemoryConflict,
    refreshSkills,
    refreshHardware,
    refreshModels,
    refreshPersonas,
    refreshFolders,
    refreshMcpServers,
    addMcpServer,
    removeMcpServer,
    toggleMcpServer,
    checkMcpTools,
    refreshAutomation,
    addWebhook,
    toggleWebhook,
    deleteWebhook,
    addRule,
    toggleRule,
    deleteRule,
    refreshSchedules,
    addSchedule,
    deleteSchedule,
    toggleSchedule,
    runScheduleNow,
    toggleExpandSchedule,
    addFolder,
    removeFolder,
    toggleFolder,
    scanFolderNow,
    addPersona,
    deletePersona,
    saveSystemPrompt,
    toggleMemoryEnabled,
    toggleNtfyEnabled,
    saveNtfyConfig,
    toggleWakeWordEnabled,
    saveWakeWordPhrase,
    toggleRecallEnabled,
    toggleAgentEnabled,
    setAgentMode,
    saveCheckCommand,
    startPairing,
    joinWithCode,
    exportSnapshot,
    importSnapshot,
    refreshEmailInbox,
    saveEmailConfig,
    testEmailConnection,
    openEmail,
    summarizeEmail,
    draftEmailReply,
    sendEmailReply,
    handlePull,
    handleCreate,
    handleDeleteModel,
    handleSetPasscode,
    handleDisablePasscode,
    handleImport,
    toggleAutoCheck,
    toggleNativeTools,
    addMemory,
    toggleMemory,
    deleteMemory,
    clearAllMemories,
    saveHost,
    setOverride,
  };

  return (
    <SettingsContext.Provider value={settingsContext}>
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
            <img className="settings-title-mark" src="/favicon.svg" alt="" aria-hidden="true" />
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
            {activeSection === "appearance" && <AppearanceSection />}

            {activeSection === "accessibility" && <AccessibilitySection />}

            {activeSection === "connection" && <ConnectionSection />}

            {activeSection === "memory" && <MemorySection />}

            {activeSection === "skills" && <SkillsSection />}

            {activeSection === "email" && <EmailSection />}

            {activeSection === "sync" && <SyncSection />}

            {activeSection === "personas" && <PersonasSection />}

            {activeSection === "agent" && <AgentSection />}

            {activeSection === "council" && <CouncilSection />}

            {activeSection === "routing" && <RoutingSection />}

            {activeSection === "models" && <ModelsSection />}

            {activeSection === "voice" && <VoiceSection />}

            {activeSection === "data" && <DataSection />}

            {activeSection === "folders" && <FoldersSection />}

            {activeSection === "schedules" && <SchedulesSection />}

            {activeSection === "automation" && <AutomationSection />}

            {activeSection === "about" && <AboutSection />}
          </div>
        </div>
      </div>
    </div>
    </SettingsContext.Provider>
  );
}