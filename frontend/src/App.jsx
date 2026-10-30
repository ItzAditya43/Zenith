import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import Composer from "./components/Composer";
import MessageBubble from "./components/MessageBubble";
import CommandPalette from "./components/CommandPalette";
import ToastStack from "./components/ToastStack";
import Icon from "./components/Icon.jsx";
import LockScreen from "./components/LockScreen.jsx";
import AccessGate from "./components/AccessGate.jsx";
import AmbientCanvas from "./components/AmbientCanvas.jsx";
import BootSplash from "./components/BootSplash";
import WakeWordListener from "./components/WakeWordListener.jsx";
import { THEME_ANIMATIONS } from "./lib/ambientAnimations";
import SelectionPopover from "./components/SelectionPopover.jsx";
import { api, authHeaders, GATE_EVENT } from "./lib/api";
import { buildCommands } from "./lib/commands.js";
import ChatHeader from "./components/ChatHeader.jsx";

// Overlay panels load on first open instead of with the app: they were ~half
// of the startup bundle and most sessions never open most of them. Each gets
// its own Suspense boundary so loading one never blanks the rest of the UI.
function lazyPanel(loader) {
  const Inner = lazy(loader);
  function LazyPanel(props) {
    return (
      <Suspense fallback={null}>
        <Inner {...props} />
      </Suspense>
    );
  }
  LazyPanel.preload = loader;
  return LazyPanel;
}
const SettingsPanel = lazyPanel(() => import("./components/SettingsPanel"));
const BranchTree = lazyPanel(() => import("./components/BranchTree.jsx"));
const DocumentEditor = lazyPanel(() => import("./components/DocumentEditor.jsx"));
const CalendarPanel = lazyPanel(() => import("./components/CalendarPanel.jsx"));
const NotesPanel = lazyPanel(() => import("./components/NotesPanel.jsx"));
const TodoPanel = lazyPanel(() => import("./components/TodoPanel.jsx"));
const ResearchDashboard = lazyPanel(() => import("./components/ResearchDashboard.jsx"));
const GroupChatPicker = lazyPanel(() => import("./components/GroupChatPicker.jsx"));
const OnboardingTour = lazyPanel(() => import("./components/OnboardingTour.jsx"));
const WhatsNewPanel = lazyPanel(() => import("./components/WhatsNewPanel.jsx"));
const UsageDashboard = lazyPanel(() => import("./components/UsageDashboard.jsx"));
const HealthPanel = lazyPanel(() => import("./components/HealthPanel.jsx"));
const TracesPanel = lazyPanel(() => import("./components/TracesPanel"));
const CodeEditorPanel = lazyPanel(() => import("./components/CodeEditorPanel.jsx"));
const SnippetsPanel = lazyPanel(() => import("./components/SnippetsPanel.jsx"));
const KnowledgeGraphPanel = lazyPanel(() => import("./components/KnowledgeGraphPanel.jsx"));
const DigestPanel = lazyPanel(() => import("./components/DigestPanel.jsx"));
const RagSourcesPanel = lazyPanel(() => import("./components/RagSourcesPanel.jsx"));
const SettingsHistoryPanel = lazyPanel(() => import("./components/SettingsHistoryPanel.jsx"));
const BatchJobPanel = lazyPanel(() => import("./components/BatchJobPanel.jsx"));
const BackupPanel = lazyPanel(() => import("./components/BackupPanel.jsx"));
const ShortcutsOverlay = lazyPanel(() => import("./components/ShortcutsOverlay.jsx"));


export default function App() {
  const [locked, setLocked] = useState(false);
  const [lockChecked, setLockChecked] = useState(false);
  const [accessGate, setAccessGate] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  // Start collapsed on narrow screens so the off-canvas sidebar doesn't
  // cover the chat on first load (phones); expanded on desktop.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => typeof window !== "undefined" && window.innerWidth <= 720
  );
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [status, setStatus] = useState("idle"); // idle | thinking | speaking
  // Live generation stats for the status rail — recomputed on every token
  // event while streaming, cleared shortly after a turn finishes.
  const [genStats, setGenStats] = useState(null); // { model, tokPerSec }
  const genStartRef = useRef(0);
  const genTokenCountRef = useRef(0);
  const [voiceReplyEnabled, setVoiceReplyEnabled] = useState(false);
  const [continuousVoice, setContinuousVoice] = useState(false);
  const [autoListenNonce, setAutoListenNonce] = useState(null);
  const [connectionError, setConnectionError] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("zenith-theme") || "oled-ember"
  );
  const [density, setDensity] = useState(() => localStorage.getItem("zenith-density") || "comfortable");
  const [fontScale, setFontScale] = useState(() => localStorage.getItem("zenith-font-scale") || "1");
  const [highContrast, setHighContrast] = useState(() => localStorage.getItem("zenith-high-contrast") === "1");
  const [reduceMotion, setReduceMotion] = useState(() => localStorage.getItem("zenith-reduce-motion") === "1");
  const [dyslexiaFont, setDyslexiaFont] = useState(() => localStorage.getItem("zenith-dyslexia-font") === "1");
  const [underlineLinks, setUnderlineLinks] = useState(() => localStorage.getItem("zenith-underline-links") === "1");
  const [ambientAnim, setAmbientAnim] = useState(() => localStorage.getItem("zenith-ambient") || "none");
  const [notificationsEnabled, setNotificationsEnabled] = useState(
    () => localStorage.getItem("zenith-notifications") === "1"
  );
  const lastRunPollRef = useRef(Date.now() / 1000);
  const [focusMode, setFocusMode] = useState(false);
  const [agentAvailable, setAgentAvailable] = useState(false);
  const [imageAvailable, setImageAvailable] = useState(false);
  const [councilModels, setCouncilModels] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [branches, setBranches] = useState({});
  const [branchTreeOpen, setBranchTreeOpen] = useState(false);
  const [seedText, setSeedText] = useState(null);
  const [projects, setProjects] = useState([]);
  const [installedModels, setInstalledModels] = useState([]);
  const [openDoc, setOpenDoc] = useState(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [todosOpen, setTodosOpen] = useState(false);
  const [researchOpen, setResearchOpen] = useState(false);
  const [codeEditorOpen, setCodeEditorOpen] = useState(false);
  const [snippetsOpen, setSnippetsOpen] = useState(false);
  const [graphOpen, setGraphOpen] = useState(false);
  const [digestOpen, setDigestOpen] = useState(false);
  const [quickActions, setQuickActions] = useState([]);
  const [contextWindow, setContextWindow] = useState(8192);
  const [maxContextMessages, setMaxContextMessages] = useState(24);
  const [onboardingOpen, setOnboardingOpen] = useState(
    () => !localStorage.getItem("zenith-onboarded")
  );
  const [whatsNewOpen, setWhatsNewOpen] = useState(false);
  const [usageOpen, setUsageOpen] = useState(false);
  const [healthOpen, setHealthOpen] = useState(false);
  const [tracesOpen, setTracesOpen] = useState(false);
  const [runFlags, setRunFlags] = useState({ agentMode: "manual", sandbox: false });
  // Warm the panels people open most once the app is idle, so first open is
  // instant without putting them back in the startup bundle.
  useEffect(() => {
    const warm = () => [SettingsPanel, HealthPanel, TracesPanel, DocumentEditor].forEach((p) => p.preload());
    const id = window.requestIdleCallback ? window.requestIdleCallback(warm, { timeout: 4000 }) : setTimeout(warm, 2000);
    return () => (window.cancelIdleCallback ? window.cancelIdleCallback(id) : clearTimeout(id));
  }, []);

  const [booting, setBooting] = useState(() => {
    try {
      return !sessionStorage.getItem("zenith-booted");
    } catch {
      return false;
    }
  });
  const finishBoot = useCallback(() => {
    try {
      sessionStorage.setItem("zenith-booted", "1");
    } catch {
      /* storage blocked: splash shows again next load, harmless */
    }
    setBooting(false);
  }, []);
  const [ragSourcesOpen, setRagSourcesOpen] = useState(false);
  const [backupOpen, setBackupOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [settingsHistoryOpen, setSettingsHistoryOpen] = useState(false);
  const [batchJobOpen, setBatchJobOpen] = useState(false);
  const [wakeWordEnabled, setWakeWordEnabled] = useState(false);
  const [wakeWordPhrase, setWakeWordPhrase] = useState("hey zenith");
  const dismissOnboarding = () => {
    localStorage.setItem("zenith-onboarded", "1");
    setOnboardingOpen(false);
  };
  const [groupPersonaIds, setGroupPersonaIds] = useState([]);
  const [groupPickerOpen, setGroupPickerOpen] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [settingsInitialSection, setSettingsInitialSection] = useState("appearance");
  const [toasts, setToasts] = useState([]);

  const showToast = (message, type = "info", duration) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setToasts((t) => [...t, { id, message, type, duration }]);
  };
  const dismissToast = (id) => setToasts((t) => t.filter((x) => x.id !== id));

  // Fire a desktop notification if the user has opted in and granted browser
  // permission. `onlyWhenHidden` limits noise for in-app completions (a turn
  // finishing) — background scheduled runs notify regardless of focus.
  const notify = (title, body, { onlyWhenHidden = false } = {}) => {
    if (!notificationsEnabled) return;
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    if (onlyWhenHidden && !document.hidden) return;
    try {
      new Notification(title, { body, tag: "zenith", icon: "/favicon.ico" });
    } catch {
      /* some browsers throw if constructed outside a user gesture — ignore */
    }
  };

  const enableNotifications = async (on) => {
    if (on && typeof Notification !== "undefined" && Notification.permission !== "granted") {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        showToast("Notifications weren't allowed by the browser.", "error");
        return;
      }
    }
    setNotificationsEnabled(on);
    localStorage.setItem("zenith-notifications", on ? "1" : "0");
  };
  const scrollRef = useRef(null);
  const audioRef = useRef(null);
  const abortRef = useRef(null);
  const titleTimerRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("zenith-theme", theme);
    // An animation picked under a previous theme might not fit this one
    // (e.g. Stars under Zen Minimal) — drop back to none rather than
    // showing something that doesn't belong.
    const allowed = THEME_ANIMATIONS[theme] || [];
    setAmbientAnim((a) => (allowed.includes(a) ? a : "none"));
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute("data-density", density);
    localStorage.setItem("zenith-density", density);
  }, [density]);

  useEffect(() => {
    document.documentElement.style.setProperty("--font-scale", fontScale);
    localStorage.setItem("zenith-font-scale", fontScale);
  }, [fontScale]);

  useEffect(() => {
    document.documentElement.toggleAttribute("data-high-contrast", highContrast);
    localStorage.setItem("zenith-high-contrast", highContrast ? "1" : "0");
  }, [highContrast]);

  useEffect(() => {
    document.documentElement.toggleAttribute("data-reduce-motion", reduceMotion);
    localStorage.setItem("zenith-reduce-motion", reduceMotion ? "1" : "0");
  }, [reduceMotion]);

  useEffect(() => {
    document.documentElement.toggleAttribute("data-dyslexia-font", dyslexiaFont);
    localStorage.setItem("zenith-dyslexia-font", dyslexiaFont ? "1" : "0");
  }, [dyslexiaFont]);

  useEffect(() => {
    document.documentElement.toggleAttribute("data-underline-links", underlineLinks);
    localStorage.setItem("zenith-underline-links", underlineLinks ? "1" : "0");
  }, [underlineLinks]);

  useEffect(() => {
    localStorage.setItem("zenith-ambient", ambientAnim);
  }, [ambientAnim]);

  // Poll for background scheduled-task completions while notifications are on,
  // so an unattended schedule that runs while you're in another tab still
  // reaches you. Only notifies for runs finished since the last poll.
  useEffect(() => {
    if (!notificationsEnabled) return;
    lastRunPollRef.current = Date.now() / 1000;
    const tick = async () => {
      try {
        const runs = await api.recentScheduleRuns(lastRunPollRef.current);
        if (runs.length) {
          lastRunPollRef.current = Math.max(...runs.map((r) => r.finished_at));
          for (const r of runs) {
            const label = r.status === "error" ? "failed" : "finished";
            notify(`Scheduled task ${label}`, r.schedule_name || "A scheduled task ran.");
          }
        }
      } catch {
        /* transient; try again next tick */
      }
    };
    const id = setInterval(tick, 30000);
    return () => clearInterval(id);
  // oxlint-disable-next-line react-hooks/exhaustive-deps -- notify is recreated every render; restarting the poller on each render would reset its cursor
  }, [notificationsEnabled]);

  useEffect(() => {
    api.getConfig().then((c) => {
      setAgentAvailable(!!c.agent_enabled);
      setCouncilModels(c.council_models || []);
      setContextWindow(c.default_context_window || 8192);
      setMaxContextMessages(c.max_context_messages || 24);
      setWakeWordEnabled(!!c.wake_word_enabled);
      setWakeWordPhrase(c.wake_word_phrase || "hey zenith");
      setRunFlags({ agentMode: c.agent_mode || "manual", sandbox: c.agent_sandbox === "docker" });
    }).catch(() => {});
    api.listPersonas().then(setPersonas).catch(() => {});
    api.listQuickActions().then(setQuickActions).catch(() => {});
  }, []);

  const handlePersonaChange = async (personaId) => {
    if (!activeId) return;
    setConversations((cs) =>
      cs.map((c) => (c.id === activeId ? { ...c, persona_id: personaId } : c))
    );
    try {
      await api.setConversationPersona(activeId, personaId);
    } catch {
      /* best-effort — a failed persona switch isn't worth blocking on */
    }
  };

  const handleSetWorkdir = async () => {
    if (!activeId) return;
    const current = activeConversation?.workdir || "";
    const input = window.prompt(
      "Working directory for this conversation — agent mode's bash cwd and relative " +
        "file paths resolve against it. Leave blank to unbind.",
      current
    );
    if (input === null) return; // cancelled
    try {
      const result = await api.setConversationWorkdir(activeId, input.trim() || null);
      setConversations((cs) =>
        cs.map((c) => (c.id === activeId ? { ...c, workdir: result.workdir } : c))
      );
      showToast(result.workdir ? `Working directory set: ${result.workdir}` : "Working directory cleared", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  const handleExtractProject = async () => {
    if (!activeId) return;
    try {
      const result = await api.extractProject(activeId);
      setConversations((cs) =>
        cs.map((c) => (c.id === activeId ? { ...c, workdir: result.workdir } : c))
      );
      showToast(`Extracted ${result.files.length} file${result.files.length === 1 ? "" : "s"} to ${result.workdir}`, "success");
      setCodeEditorOpen(true);
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  const handleShare = async () => {
    if (!activeId) return;
    try {
      if (activeConversation?.share_token) {
        await api.unshareConversation(activeId);
        setConversations((cs) => cs.map((c) => (c.id === activeId ? { ...c, share_token: null } : c)));
        showToast("Share link revoked.", "success");
        return;
      }
      const { token } = await api.shareConversation(activeId);
      setConversations((cs) => cs.map((c) => (c.id === activeId ? { ...c, share_token: token } : c)));
      const url = api.shareUrl(token);
      try {
        await navigator.clipboard.writeText(url);
        showToast("Share link copied to clipboard.", "success");
      } catch {
        showToast(`Share link: ${url}`, "success");
      }
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  const handleSetProjectAgentMode = async (project) => {
    const input = window.prompt(
      "Agent autonomy for this project (manual/semi/full/plan) — leave blank to use the global default:",
      project.agent_mode || ""
    );
    if (input === null) return;
    const mode = input.trim() || null;
    if (mode && !["manual", "semi", "full", "plan"].includes(mode)) {
      showToast("Must be one of: manual, semi, full, plan.", "error");
      return;
    }
    try {
      await api.setProjectAgentMode(project.id, mode);
      setProjects((ps) => ps.map((p) => (p.id === project.id ? { ...p, agent_mode: mode } : p)));
      showToast(mode ? `Agent autonomy pinned to "${mode}" for ${project.name}.` : `Agent autonomy reset to global default for ${project.name}.`, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  const handleTogglePin = async (c) => {
    try {
      await api.setConversationPinned(c.id, !c.pinned);
      setConversations((cs) => cs.map((x) => (x.id === c.id ? { ...x, pinned: !c.pinned } : x)));
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  const handleEditTags = async (c) => {
    const input = window.prompt("Tags (comma-separated):", (c.tags || []).join(", "));
    if (input === null) return;
    const tags = input.split(",").map((t) => t.trim()).filter(Boolean);
    try {
      await api.setConversationTags(c.id, tags);
      setConversations((cs) => cs.map((x) => (x.id === c.id ? { ...x, tags } : x)));
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  const refreshConversations = async () => {
    try {
      const list = await api.listConversations();
      setConversations(list);
    } catch (err) {
      setConnectionError(err.message);
    }
  };

  const refreshProjects = () => {
    api.listProjects().then(setProjects).catch(() => {});
  };

  const handleCreateProject = async () => {
    const name = window.prompt("Project name?");
    if (!name || !name.trim()) return;
    try {
      await api.createProject(name.trim());
      refreshProjects();
      showToast(`Project "${name.trim()}" created.`, "success");
    } catch (err) {
      showToast(err.message || "Couldn't create project", "error");
    }
  };

  // Passcode lock: on load, ask the backend whether a lock is set. If it is
  // and we don't already hold a valid unlock token this tab session, show
  // the lock screen before anything else loads.
  useEffect(() => {
    refreshProjects();
    const loadModels = (attempt = 0) => {
      api
        .listModels()
        .then((ms) => setInstalledModels(ms.map((m) => m.name)))
        .catch(() => {
          if (attempt < 6) setTimeout(() => loadModels(attempt + 1), 700);
        });
    };
    loadModels();
  }, []);

  useEffect(() => {
    api.imageStatus().then(({ configured }) => setImageAvailable(configured)).catch(() => {});
  }, []);

  useEffect(() => {
    const onGate = (e) => setAccessGate(e.detail);
    window.addEventListener(GATE_EVENT, onGate);
    return () => window.removeEventListener(GATE_EVENT, onGate);
  }, []);

  useEffect(() => {
    api
      .lockStatus()
      .then(({ enabled }) => {
        setLocked(enabled && !sessionStorage.getItem("zenith-unlock"));
        setLockChecked(true);
      })
      .catch(() => setLockChecked(true));
  }, []);

  const [retryAttempt, setRetryAttempt] = useState(0);
  const [manualRetryNonce, setManualRetryNonce] = useState(0);
  const [isOffline, setIsOffline] = useState(
    () => typeof navigator !== "undefined" && navigator.onLine === false
  );

  // Browser-level connectivity (Wi-Fi/LAN down) is a different failure mode
  // than "backend unreachable" below — surface both distinctly rather than
  // one generic error, since the fix differs (reconnect network vs. check
  // Ollama/Docker).
  useEffect(() => {
    const goOnline = () => {
      setIsOffline(false);
      showToast("Back online.", "success");
      setManualRetryNonce((n) => n + 1); // immediately retry the backend connection
    };
    const goOffline = () => {
      setIsOffline(true);
      showToast("You're offline — check your network connection.", "error");
    };
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  useEffect(() => {
    // The bundled backend can take a while to boot on a first launch or a
    // slower machine. Retry with a capped backoff for as long as this window
    // is open, so a late sidecar startup never leaves the app disconnected.
    let cancelled = false;
    const loadWithRetry = async (attempt = 0) => {
      setRetryAttempt(attempt);
      try {
        const list = await api.listConversations();
        if (cancelled) return;
        setConversations(list);
        if (list.length > 0) {
          selectConversation(list[0].id);
        } else {
          const conv = await api.createConversation();
          setConversations([conv]);
          setActiveId(conv.id);
        }
        setConnectionError(null);
        setRetryAttempt(0);
      } catch (err) {
        if (cancelled) return;
        if (attempt >= 6) setConnectionError(err.message);
        setTimeout(() => loadWithRetry(attempt + 1), Math.min(700 * 2 ** attempt, 8000));
      }
    };
    loadWithRetry();
    return () => {
      cancelled = true;
    };
  }, [manualRetryNonce]);

  const [isNearBottom, setIsNearBottom] = useState(true);

  useEffect(() => {
    // Don't yank the view back down if the user has deliberately
    // scrolled up to (re)read something while a reply keeps streaming in.
    if (isNearBottom) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  // oxlint-disable-next-line react-hooks/exhaustive-deps -- auto-scroll on new content only; scrolling when isNearBottom flips would fight the user
  }, [messages]);

  const handleChatScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setIsNearBottom(distanceFromBottom < 120);
  };

  const scrollToBottom = () => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    setIsNearBottom(true);
  };

  // Keyboard shortcuts (Tier 6 #6) — skip when typing in inputs
  useEffect(() => {
    const handler = (e) => {
      const tag = e.target.tagName;
      const isInput = tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable;
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen((v) => !v);
      } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        // Send is handled in Composer; this is a no-op placeholder for focus.
      } else if ((e.metaKey || e.ctrlKey) && e.key === ".") {
        e.preventDefault();
        setFocusMode((v) => !v);
      } else if (e.key === "?" && !isInput) {
        e.preventDefault();
        setShortcutsOpen((v) => !v);
      } else if (e.key === "Escape") {
        if (shortcutsOpen) {
          setShortcutsOpen(false);
          return;
        }
        if (commandPaletteOpen) {
          setCommandPaletteOpen(false);
          return;
        }
        if (focusMode) {
          setFocusMode(false);
          return;
        }
        if (isInput) return; // let inputs handle Escape themselves (blur, etc.)
        setSettingsOpen(false);
        setSearchResults(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [commandPaletteOpen, focusMode, shortcutsOpen]);

  const refreshBranches = async (id) => {
    try {
      setBranches(await api.listBranches(id));
    } catch {
      /* branch switcher is a nice-to-have — a failed fetch just hides it */
    }
  };

  const selectConversation = async (id) => {
    setActiveId(id);
    setSearchResults(null);
    if (window.innerWidth <= 720) setSidebarCollapsed(true); // close off-canvas sidebar on mobile
    const msgs = await api.getMessages(id);
    setMessages(msgs);
    refreshBranches(id);
    api.getGroupPersonas(id).then((r) => setGroupPersonaIds(r.persona_ids || [])).catch(() => setGroupPersonaIds([]));
  };

  const handleSwitchBranch = async (messageId) => {
    if (!activeId) return;
    try {
      const result = await api.activateBranch(activeId, messageId);
      setMessages(result.messages);
      refreshBranches(activeId);
    } catch {
      /* best-effort */
    }
  };

  const handleDeleteMessage = async (message) => {
    if (!window.confirm("Delete this message and everything after it in this branch?")) return;
    // A not-yet-persisted (optimistic) message only exists in local state.
    if (!message.id || String(message.id).startsWith("local")) {
      setMessages((m) => m.filter((x) => x.id !== message.id));
      return;
    }
    try {
      const result = await api.deleteMessage(activeId, message.id);
      setMessages(result.messages);
      refreshBranches(activeId);
      showToast(`Deleted ${result.deleted} message${result.deleted === 1 ? "" : "s"}.`, "success");
    } catch (err) {
      showToast(err.message || "Delete failed", "error");
    }
  };

  const handleCreate = async (projectId = null) => {
    const conv = await api.createConversation("New chat", projectId);
    setConversations((c) => [conv, ...c]);
    setActiveId(conv.id);
    setMessages([]);
    if (window.innerWidth <= 720) setSidebarCollapsed(true); // phones: drawer closes after choosing
  };

  const handleDelete = async (id) => {
    // Tier 6 #16 — confirm before destroying history.
    if (!window.confirm("Delete this conversation? This can't be undone.")) return;
    await api.deleteConversation(id);
    const remaining = conversations.filter((c) => c.id !== id);
    setConversations(remaining);
    if (id === activeId) {
      if (remaining.length > 0) selectConversation(remaining[0].id);
      else handleCreate();
    }
  };

  const playReply = async (text) => {
    try {
      setStatus("speaking");
      await setAudioAndPlay(text);
    } catch {
      setStatus("idle");
    }
  };

  const setAudioAndPlay = async (text) => {
    const res = await fetch(api.speakUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      setStatus("idle");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    if (audioRef.current) {
      audioRef.current.src = url;
      audioRef.current.onended = () => {
        setStatus("idle");
        // Continuous mode: hand the mic back the instant the reply finishes
        // speaking, so the conversation keeps flowing hands-free.
        if (continuousVoice) setAutoListenNonce(Date.now());
      };
      await audioRef.current.play();
    }
  };

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setStatus("idle");
    setMessages((m) =>
      m.map((msg) => (msg.streaming ? { ...msg, streaming: false, interrupted: true } : msg))
    );
  };

  const setToolCallStatus = (toolCallId, status) => {
    setMessages((m) =>
      m.map((msg) => ({
        ...msg,
        toolCalls: (msg.toolCalls || []).map((tc) =>
          tc.id === toolCallId ? { ...tc, status } : tc
        ),
      }))
    );
  };

  const handleApproveTool = async (toolCallId) => {
    setToolCallStatus(toolCallId, "approving");
    try {
      await api.approveToolCall(toolCallId);
    } catch {
      setToolCallStatus(toolCallId, "pending");
    }
  };

  const handleDenyTool = async (toolCallId) => {
    setToolCallStatus(toolCallId, "denied");
    try {
      await api.denyToolCall(toolCallId);
    } catch {
      /* the tool_denied SSE event, or the approval timeout, will settle it */
    }
  };

  const handleRevertTool = async (toolCallId) => {
    try {
      const { message } = await api.revertToolCall(toolCallId);
      setToolCallStatus(toolCallId, "reverted");
      showToast(message, "success");
    } catch (err) {
      showToast(err.message || "Revert failed", "error");
    }
  };

  // Plan-first mode reuses the same approve/deny endpoints (the backend
  // awaits approval on the plan id exactly like a tool-call id). The
  // plan_approved/plan_rejected SSE events settle the card's status.
  const handlePlanDecision = async (planId, approved) => {
    try {
      await (approved ? api.approveToolCall(planId) : api.denyToolCall(planId));
    } catch {
      /* the plan_approved/plan_rejected SSE event or timeout will settle it */
    }
  };

  // Terminal-style keys while a turn is live: y / n settle the waiting tool
  // call or plan, Esc stops the reply (the spinner promises it). Ignored
  // while typing or with modifiers, and when overlays own the keyboard.
  const liveKeys = useRef({});
  liveKeys.current = { messages, handleApproveTool, handleDenyTool, handlePlanDecision, handleStop,
    overlayOpen: commandPaletteOpen || shortcutsOpen || settingsOpen };
  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
      const t = e.target;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return;
      const k = liveKeys.current;
      if (k.overlayOpen) return;
      const live = [...k.messages].reverse().find((m) => m.streaming);
      if (!live) return;
      if (e.key === "Escape") {
        e.preventDefault();
        k.handleStop();
        return;
      }
      if (e.key !== "y" && e.key !== "n") return;
      const approve = e.key === "y";
      const call = (live.toolCalls || []).find((tc) => tc.status === "pending");
      if (call) {
        e.preventDefault();
        (approve ? k.handleApproveTool : k.handleDenyTool)(call.id);
      } else if (live.plan?.status === "pending") {
        e.preventDefault();
        k.handlePlanDecision(live.plan.id, approve);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);


  const maybeGenerateTitle = (convId, firstUserText) => {
    // Tier 6 #4 — auto-title after first user message.
    if (titleTimerRef.current) clearTimeout(titleTimerRef.current);
    titleTimerRef.current = setTimeout(async () => {
      try {
        const { title } = await api.setTitle(convId, firstUserText);
        if (title) {
          setConversations((cs) => cs.map((c) => (c.id === convId ? { ...c, title } : c)));
          showToast(`Renamed to "${title}"`, "success");
        }
      } catch {
        /* title is best-effort */
      }
    }, 1200);
  };

  const handleCouncilSend = async (text, attachmentIds, modelsOverride = null) => {
    const models = modelsOverride && modelsOverride.length >= 2 ? modelsOverride : councilModels;
    if (!activeId || models.length < 2) return;
    const userMsg = { id: `local-${Date.now()}`, role: "user", content: text, attachments: [] };
    const assistantMsg = {
      id: `local-assistant-${Date.now()}`,
      role: "assistant",
      content: `Asking ${models.length} models…`,
      streaming: true,
      model: null,
      route_role: "council",
    };
    setMessages((m) => [...m, userMsg, assistantMsg]);
    setStatus("thinking");
    setConnectionError(null);

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const progress = {}; // model -> chars streamed so far
    const renderProgress = () =>
      models.map((m) => `${m}: ${progress[m] || 0} chars`).join(" · ");

    await api.streamCouncil(
      { conversationId: activeId, message: text, attachmentIds, models },
      (event) => {
        if (event.type === "council_token") {
          progress[event.model] = (progress[event.model] || 0) + event.text.length;
          setMessages((m) =>
            m.map((msg) => (msg.id === assistantMsg.id ? { ...msg, content: renderProgress() } : msg))
          );
        } else if (event.type === "council_error") {
          progress[event.model] = `error: ${event.message}`;
        } else if (event.type === "error") {
          setConnectionError(event.message);
          setStatus("idle");
        }
      },
      controller.signal
    );
    if (abortRef.current === controller) abortRef.current = null;

    try {
      setMessages(await api.getMessages(activeId));
      refreshBranches(activeId);
    } catch {
      /* best-effort reconciliation */
    }
    setStatus("idle");
  };

  const handleImageSend = async (text) => {
    if (!activeId || !text.trim()) return;
    const userMsg = { id: `local-${Date.now()}`, role: "user", content: text, attachments: [] };
    const assistantMsg = {
      id: `local-assistant-${Date.now()}`,
      role: "assistant",
      content: "",
      streaming: true,
      model: null,
      route_role: "vision",
    };
    setMessages((m) => [...m, userMsg, assistantMsg]);
    setStatus("thinking");
    try {
      const { images } = await api.generateImage(text);
      const urls = (images || []).map((b64) =>
        b64.startsWith("data:") ? b64 : `data:image/png;base64,${b64}`
      );
      setMessages((m) =>
        m.map((msg) =>
          msg.id === assistantMsg.id
            ? { ...msg, streaming: false, content: `*${text}*`, generatedImages: urls }
            : msg
        )
      );
    } catch (err) {
      setMessages((m) =>
        m.map((msg) =>
          msg.id === assistantMsg.id
            ? { ...msg, streaming: false, interrupted: true, interrupted_reason: err.message || "Image generation failed" }
            : msg
        )
      );
    } finally {
      setStatus("idle");
    }
  };

  const handleGroupSend = async (text) => {
    if (!activeId || !text.trim()) return;
    const userMsg = { id: `local-user-${Date.now()}`, role: "user", content: text };
    setMessages((m) => [...m, userMsg]);
    setStatus("thinking");
    const bySpeaker = {};
    await api.streamGroupChat(activeId, text, (ev) => {
      if (ev.type === "speaker_start") {
        const persona = personas.find((p) => p.id === ev.persona_id);
        const localId = `local-group-${ev.persona_id}-${Date.now()}`;
        bySpeaker[ev.persona_id] = localId;
        setMessages((m) => [
          ...m,
          {
            id: localId, role: "assistant", content: "", streaming: true,
            speaker_persona_id: ev.persona_id,
            speakerName: persona?.name || "Bot",
            speakerIcon: persona?.icon || "",
          },
        ]);
      } else if (ev.type === "token") {
        const localId = bySpeaker[ev.persona_id];
        if (!localId) return;
        setMessages((m) => m.map((msg) => (msg.id === localId ? { ...msg, content: msg.content + ev.text } : msg)));
      } else if (ev.type === "speaker_done") {
        const localId = bySpeaker[ev.persona_id];
        if (!localId) return;
        setMessages((m) => m.map((msg) => (msg.id === localId ? { ...msg, id: ev.message_id, content: ev.text, streaming: false } : msg)));
      } else if (ev.type === "error") {
        showToast(ev.message, "error");
      } else if (ev.type === "done") {
        setStatus("idle");
        selectConversation(activeId); // reconcile with persisted state
      }
    });
    setStatus("idle");
  };

  const handleSend = async (
    text,
    attachmentIds,
    editContext = null,
    webSearch = false,
    agentMode = false,
    deepResearch = false,
    regenerateOf = null,
    councilMode = false,
    imageMode = false,
    modelOverride = null,
    compareModels = null
  ) => {
    if (!activeId) return;
    if (councilMode) return handleCouncilSend(text, attachmentIds, compareModels);
    if (imageMode) return handleImageSend(text);
    if (groupPersonaIds.length >= 2) return handleGroupSend(text);
    const editOf = editContext?.messageId || null;

    let assistantMsg;
    if (regenerateOf) {
      // No new user bubble — replace the target assistant reply in place.
      assistantMsg = {
        id: `local-assistant-${Date.now()}`,
        role: "assistant",
        content: "",
        streaming: true,
        model: null,
        route_role: null,
      };
      setMessages((m) => m.map((msg) => (msg.id === regenerateOf ? assistantMsg : msg)));
    } else {
      const userMsg = { id: `local-${Date.now()}`, role: "user", content: text, attachments: [] };
      assistantMsg = {
        id: `local-assistant-${Date.now()}`,
        role: "assistant",
        content: "",
        streaming: true,
        model: null,
        route_role: null,
      };
      if (editOf) {
        // Optimistically drop the edited message + everything after it;
        // the post-stream refetch below reconciles with server truth
        // (branch structure, real ids) either way.
        const idx = messages.findIndex((m) => m.id === editOf);
        const base = idx >= 0 ? messages.slice(0, idx) : messages;
        setMessages([...base, userMsg, assistantMsg]);
      } else {
        setMessages((m) => [...m, userMsg, assistantMsg]);
      }
    }
    setStatus("thinking");
    setConnectionError(null);

    // Cancel any in-flight stream before starting a new one (Tier 1 #7).
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Auto-title on first user message of a fresh conversation.
    const conv = conversations.find((c) => c.id === activeId);
    if (!regenerateOf && conv && (conv.title === "New chat" || !conv.title)) {
      maybeGenerateTitle(activeId, text);
    }

    let fullText = "";
    let thinkingText = "";
    let thinkingStartedAt = 0;
    let thoughtFor = 0;
    let flushScheduled = false;
    const flushText = () => {
      flushScheduled = false;
      const text = fullText;
      setMessages((m) =>
        m.map((msg) =>
          msg.id === assistantMsg.id ? { ...msg, content: text, ...(thoughtFor ? { thoughtMs: thoughtFor } : {}) } : msg
        )
      );
    };
    await api.streamChat(
      { conversationId: activeId, message: text, attachmentIds, webSearch, agentMode, deepResearch, editOf, regenerateOf, modelOverride },
      (event) => {
        if (event.type === "route") {
          genStartRef.current = Date.now();
          genTokenCountRef.current = 0;
          setGenStats({ model: event.model, tokPerSec: 0 });
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? {
                    ...msg,
                    model: event.model,
                    route_role: event.role,
                    route_reason: event.reason,
                    confidence: event.confidence,
                  }
                : msg
            )
          );
        } else if (event.type === "downgrade") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? {
                    ...msg,
                    model: event.to,
                    route_reason: `Original model '${event.from}' failed mid-stream — downgraded to '${event.to}'.`,
                  }
                : msg
            )
          );
        } else if (event.type === "sources") {
          setMessages((m) =>
            m.map((msg) => (msg.id === assistantMsg.id ? { ...msg, sources: event.sources } : msg))
          );
        } else if (event.type === "memory_saved") {
          const [first, ...rest] = event.facts;
          showToast(
            rest.length ? `Remembered: "${first}" (+${rest.length} more)` : `Remembered: "${first}"`,
            "success"
          );
        } else if (event.type === "tool_call") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? {
                    ...msg,
                    toolCalls: [
                      ...(msg.toolCalls || []),
                      { id: event.id, tool: event.tool, args: event.args, risk: event.risk, diff: event.diff, status: "running" },
                    ],
                  }
                : msg
            )
          );
        } else if (event.type === "tool_pending") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? {
                    ...msg,
                    toolCalls: (msg.toolCalls || []).map((tc) =>
                      tc.id === event.id ? { ...tc, status: "pending" } : tc
                    ),
                  }
                : msg
            )
          );
        } else if (event.type === "tool_result") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? {
                    ...msg,
                    toolCalls: (msg.toolCalls || []).map((tc) =>
                      tc.id === event.id ? { ...tc, status: "done", result: event.result } : tc
                    ),
                  }
                : msg
            )
          );
        } else if (event.type === "tool_denied") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? {
                    ...msg,
                    toolCalls: (msg.toolCalls || []).map((tc) =>
                      tc.id === event.id ? { ...tc, status: "denied" } : tc
                    ),
                  }
                : msg
            )
          );
        } else if (event.type === "plan_pending") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? { ...msg, plan: { id: event.id, text: event.plan, status: "pending" } }
                : msg
            )
          );
        } else if (event.type === "plan_approved" || event.type === "plan_rejected") {
          const status = event.type === "plan_approved" ? "approved" : "rejected";
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id && msg.plan
                ? { ...msg, plan: { ...msg.plan, status } }
                : msg
            )
          );
        } else if (event.type === "thinking") {
          // Live reasoning from a thinking model (never part of the reply).
          thinkingText += event.text;
          if (!thinkingStartedAt) thinkingStartedAt = Date.now();
          setMessages((m) =>
            m.map((msg) => (msg.id === assistantMsg.id ? { ...msg, thinking: thinkingText } : msg))
          );
        } else if (event.type === "token") {
          fullText += event.text;
          if (thinkingStartedAt && !thoughtFor) thoughtFor = Date.now() - thinkingStartedAt;
          // One render per animation frame instead of one per token: an even
          // cadence for bursty local models, and far less work on fast ones.
          if (!flushScheduled) {
            flushScheduled = true;
            requestAnimationFrame(flushText);
          }
          genTokenCountRef.current += 1;
          const elapsed = (Date.now() - genStartRef.current) / 1000;
          if (elapsed > 0.3) {
            setGenStats((s) => (s ? { ...s, tokPerSec: genTokenCountRef.current / elapsed } : s));
          }
        } else if (event.type === "resumed") {
          showToast("Resuming from where the last run left off…", "info");
        } else if (event.type === "done") {
          const finalText = fullText;
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? { ...msg, streaming: false, content: finalText || msg.content }
                : msg
            )
          );
          setTimeout(() => setGenStats(null), 2500); // let the final tok/s linger briefly
          if (event.checkpointed) {
            showToast("Run paused at the step limit — send a message to continue.", "info", 6000);
          }
          if (event.new_skill) {
            showToast(`New skill saved: "${event.new_skill.name}" — find it in Settings → Skills.`, "info", 6000);
          }
          setConversations((cs) =>
            cs.map((c) => (c.id === activeId ? { ...c, updated_at: Date.now() / 1000 } : c))
          );
          if (voiceReplyEnabled && fullText.trim()) {
            playReply(fullText);
          } else {
            setStatus("idle");
          }
          // Notify when the tab is backgrounded and the user opted in.
          notify("Zenith", "Your response is ready.", { onlyWhenHidden: true });
        } else if (event.type === "error") {
          setConnectionError(event.message);
          setStatus("idle");
          // Tier 1 #7: never leave the bubble stuck in "streaming" — mark it
          // interrupted so MessageBubble can show a retry affordance.
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? {
                    ...msg,
                    streaming: false,
                    interrupted: true,
                    interrupted_reason: event.message,
                    content: msg.content || event.message,
                  }
                : msg
            )
          );
        }
      },
      controller.signal
    );
    if (abortRef.current === controller) abortRef.current = null;

    // Edit/regenerate change the branch structure server-side (hiding the
    // old subtree, new parent_ids) — reconcile local state with the
    // authoritative list rather than trust the optimistic splice above.
    if (editOf || regenerateOf) {
      try {
        setMessages(await api.getMessages(activeId));
        refreshBranches(activeId);
      } catch {
        /* keep optimistic state if the refetch itself fails */
      }
    }
  };

  const handleRetry = async (msg) => {
    // Find the user turn immediately before the interrupted assistant turn
    // and resend it.
    const idx = messages.findIndex((m) => m.id === msg.id);
    if (idx < 0) return;
    let userText = "";
    const attachments = [];
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (messages[i].role === "user") {
        userText = messages[i].content;
        break;
      }
    }
    if (!userText) return;
    // Drop the failed assistant message so the retry produces a clean chain.
    setMessages((m) => m.filter((mm) => mm.id !== msg.id));
    await handleSend(userText, attachments);
  };

  const handleRegenerate = async (msg) => {
    // Branch-aware regenerate: the backend hides the old reply and
    // creates a fresh sibling under the same user message — the original
    // is never lost, just switched away from (see the branch switcher).
    await handleSend("", [], null, false, false, false, msg.id);
  };

  const handleEdit = async (msg, newText) => {
    await handleSend(newText, [], { messageId: msg.id });
  };

  const runSearch = async (q) => {
    setSearchQuery(q);
    if (!q.trim()) {
      setSearchResults(null);
      return;
    }
    try {
      const results = await api.searchAll(q);
      setSearchResults(results);
    } catch {
      setSearchResults({ conversations: [], documents: [], memories: [] });
    }
  };

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeId),
    [conversations, activeId]
  );

  const openSettingsAt = (section) => {
    setSettingsInitialSection(section);
    setSettingsOpen(true);
  };

  // The palette list is memoised, so its actions must not close over
  // handlers directly — that froze them at whatever state existed when the
  // list was last rebuilt (an auto-send quick action used stale composer
  // settings). Actions read the latest handlers through this ref instead.
  // Starters for the empty chat: pick up recent threads first, then defaults.
  const emptySuggestions = useMemo(() => {
    const recent = conversations
      .filter((c) => c.id !== activeId && c.title && !/^new chat$/i.test(c.title))
      .slice(0, 2)
      .map((c) => `Pick up where we left off on “${c.title}”`);
    const defaults = [
      "Summarise a document I'll attach",
      "Plan my week from my to-do list",
      "Explain the last error I got",
    ];
    return [...recent, ...defaults].slice(0, 3);
  }, [conversations, activeId]);

  const paletteHandlers = useRef({});
  paletteHandlers.current = { handleSend, handleSetWorkdir, handlePersonaChange };

  const commands = useMemo(
    () =>
      buildCommands({
        conversations,
        sidebarCollapsed,
        setSidebarCollapsed,
        voiceReplyEnabled,
        setVoiceReplyEnabled,
        density,
        setDensity,
        focusMode,
        setFocusMode,
        agentAvailable,
        personas,
        setSeedText,
        quickActions,
        setOnboardingOpen,
        setWhatsNewOpen,
        setTracesOpen,
        setShortcutsOpen,
        selectConversation,
        handleCreate,
        activeConversation,
        openSettingsAt,
        paletteHandlers,
      }),
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- handlers are read via paletteHandlers (latest), not captured
    [conversations, personas, activeConversation, sidebarCollapsed, voiceReplyEnabled, focusMode, density, quickActions, agentAvailable],
  );

  if (accessGate) return <AccessGate kind={accessGate.kind} message={accessGate.message} />;
  if (!lockChecked) return null; // avoid a flash of the app before we know
  if (booting && !locked) return <BootSplash onDone={finishBoot} />;
  if (locked) return <LockScreen onUnlocked={() => window.location.reload()} />;

  return (
    <div className={`app-shell ${focusMode ? "app-shell-focus" : ""}`}>
      <a href="#chat-main-content" className="skip-link">Skip to chat</a>
      <AmbientCanvas animationId={ambientAnim} />
      <WakeWordListener
        enabled={wakeWordEnabled}
        phrase={wakeWordPhrase}
        onWake={() => setAutoListenNonce(Date.now())}
      />
      {!focusMode && (
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          onSelect={selectConversation}
          onCreate={handleCreate}
          onDelete={handleDelete}
          onOpenSettings={() => setSettingsOpen(true)}
          onOpenMemory={() => openSettingsAt("memory")}
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
          searchQuery={searchQuery}
          onSearch={runSearch}
          searchResults={searchResults}
          projects={projects}
          onCreateProject={handleCreateProject}
          onCreateInProject={handleCreate}
          onOpenNotes={() => setNotesOpen(true)}
          onOpenTodos={() => setTodosOpen(true)}
          onOpenCalendar={() => setCalendarOpen(true)}
          onOpenResearch={() => setResearchOpen(true)}
          onTogglePin={handleTogglePin}
          onEditTags={handleEditTags}
          onSetProjectAgentMode={handleSetProjectAgentMode}
        />
      )}

      {!focusMode && !sidebarCollapsed && (
        <div
          className="sidebar-backdrop"
          onClick={() => setSidebarCollapsed(true)}
          aria-hidden="true"
        />
      )}

      <main className={`chat-main ${openDoc ? "chat-main-split" : ""}`} id="chat-main-content">
        <div className="chat-column">
        <ChatHeader
          activeId={activeId}
          messages={messages}
          setSidebarCollapsed={setSidebarCollapsed}
          genStats={genStats}
          voiceReplyEnabled={voiceReplyEnabled}
          setVoiceReplyEnabled={setVoiceReplyEnabled}
          continuousVoice={continuousVoice}
          setContinuousVoice={setContinuousVoice}
          focusMode={focusMode}
          setFocusMode={setFocusMode}
          agentAvailable={agentAvailable}
          personas={personas}
          branches={branches}
          branchTreeOpen={branchTreeOpen}
          setBranchTreeOpen={setBranchTreeOpen}
          calendarOpen={calendarOpen}
          setCalendarOpen={setCalendarOpen}
          notesOpen={notesOpen}
          setNotesOpen={setNotesOpen}
          todosOpen={todosOpen}
          setTodosOpen={setTodosOpen}
          researchOpen={researchOpen}
          setResearchOpen={setResearchOpen}
          codeEditorOpen={codeEditorOpen}
          setCodeEditorOpen={setCodeEditorOpen}
          snippetsOpen={snippetsOpen}
          setSnippetsOpen={setSnippetsOpen}
          graphOpen={graphOpen}
          setGraphOpen={setGraphOpen}
          digestOpen={digestOpen}
          setDigestOpen={setDigestOpen}
          setQuickActions={setQuickActions}
          usageOpen={usageOpen}
          setUsageOpen={setUsageOpen}
          healthOpen={healthOpen}
          setHealthOpen={setHealthOpen}
          ragSourcesOpen={ragSourcesOpen}
          setRagSourcesOpen={setRagSourcesOpen}
          backupOpen={backupOpen}
          setBackupOpen={setBackupOpen}
          settingsHistoryOpen={settingsHistoryOpen}
          setSettingsHistoryOpen={setSettingsHistoryOpen}
          batchJobOpen={batchJobOpen}
          setBatchJobOpen={setBatchJobOpen}
          groupPersonaIds={groupPersonaIds}
          setGroupPickerOpen={setGroupPickerOpen}
          handlePersonaChange={handlePersonaChange}
          handleSetWorkdir={handleSetWorkdir}
          handleExtractProject={handleExtractProject}
          handleShare={handleShare}
          activeConversation={activeConversation}
          openSettingsAt={openSettingsAt}
        />

        {onboardingOpen && <OnboardingTour onClose={dismissOnboarding} />}
        {whatsNewOpen && <WhatsNewPanel onClose={() => setWhatsNewOpen(false)} />}
        {calendarOpen && <CalendarPanel onClose={() => setCalendarOpen(false)} />}
        {notesOpen && <NotesPanel onClose={() => setNotesOpen(false)} />}
        {todosOpen && <TodoPanel onClose={() => setTodosOpen(false)} />}
        {researchOpen && <ResearchDashboard onClose={() => setResearchOpen(false)} />}
        {snippetsOpen && (
          <SnippetsPanel
            onClose={() => setSnippetsOpen(false)}
            onInsert={(text) => {
              setSeedText({ text, nonce: Date.now() });
              setSnippetsOpen(false);
            }}
            onRunQuickAction={(action) => {
              setSnippetsOpen(false);
              if (action.auto_send) {
                handleSend(action.prompt_template, []);
              } else {
                setSeedText({ text: action.prompt_template, nonce: Date.now() });
              }
            }}
          />
        )}
        {graphOpen && (
          <KnowledgeGraphPanel
            onClose={() => setGraphOpen(false)}
            onOpenConversation={(id) => selectConversation(id)}
          />
        )}
        {digestOpen && <DigestPanel onClose={() => setDigestOpen(false)} />}
        {codeEditorOpen && activeConversation?.workdir && (
          <CodeEditorPanel
            conversationId={activeId}
            workdir={activeConversation.workdir}
            onClose={() => setCodeEditorOpen(false)}
          />
        )}
        {usageOpen && <UsageDashboard onClose={() => setUsageOpen(false)} />}
        {healthOpen && <HealthPanel onClose={() => setHealthOpen(false)} />}
        {tracesOpen && <TracesPanel conversationId={activeConversation?.id} onClose={() => setTracesOpen(false)} />}
        {ragSourcesOpen && <RagSourcesPanel onClose={() => setRagSourcesOpen(false)} />}
        {settingsHistoryOpen && <SettingsHistoryPanel onClose={() => setSettingsHistoryOpen(false)} />}
        {batchJobOpen && <BatchJobPanel onClose={() => setBatchJobOpen(false)} />}
        {backupOpen && <BackupPanel onClose={() => setBackupOpen(false)} />}
        {shortcutsOpen && <ShortcutsOverlay onClose={() => setShortcutsOpen(false)} />}
        {groupPickerOpen && (
          <GroupChatPicker
            personas={personas}
            selectedIds={groupPersonaIds}
            onChange={(ids) => {
              setGroupPersonaIds(ids);
              api.setGroupPersonas(activeId, ids.length >= 2 ? ids : null).catch(() => {});
            }}
            onClose={() => setGroupPickerOpen(false)}
          />
        )}

        {branchTreeOpen && (
          <BranchTree
            branches={branches}
            messages={messages}
            onSwitchBranch={(id) => {
              handleSwitchBranch(id);
              setBranchTreeOpen(false);
            }}
            onClose={() => setBranchTreeOpen(false)}
          />
        )}

        {isOffline && (
          <div className="banner-error" role="alert">
            You're offline — Zenith needs a network connection to reach its backend, even on your
            own LAN.
          </div>
        )}

        {!isOffline && connectionError && (
          <div className="banner-error" role="alert">
            Can't reach the Zenith backend: {connectionError}
            <button onClick={() => setManualRetryNonce((n) => n + 1)}>Retry now</button>
            <button onClick={() => setSettingsOpen(true)}>Open settings</button>
          </div>
        )}

        {!connectionError && retryAttempt > 0 && (
          <div className="banner-error" role="status">
            Reconnecting to the backend… (attempt {retryAttempt + 1})
          </div>
        )}

        <div
          className="chat-scroll"
          ref={scrollRef}
          onScroll={handleChatScroll}
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          aria-label="Conversation messages"
        >
          <SelectionPopover
            containerRef={scrollRef}
            onExplain={(text) => setSeedText({ text: `Explain this: "${text}"`, nonce: Date.now() })}
            onAsk={(text) => setSeedText({ text: `About this: "${text}"\n`, nonce: Date.now() })}
          />
          {messages.length === 0 && (
            <div className="empty-state">
              <img className="empty-state-logo" src="/favicon.svg" alt="" aria-hidden="true" />
              <h2>Everything runs on your machine.</h2>
              <p>
                Type, drop an image, upload a document, or hold the mic — Zenith reads
                what's installed on your Ollama and routes the turn automatically.
              </p>
              <div className="empty-state-suggestions" role="group" aria-label="Suggestions">
                {emptySuggestions.map((sug) => (
                  <button
                    key={sug}
                    className="empty-state-suggestion"
                    onClick={() => setSeedText({ text: sug, nonce: Date.now() })}
                  >
                    {sug}
                  </button>
                ))}
              </div>
              <div className="empty-state-features">
                <div className="empty-state-feature">
                  <span className="empty-state-feature-icon"><Icon name="search" size={18} /></span>
                  <div>
                    <strong>Web search &amp; research</strong>
                    <span>Pick a mode from the composer to search or investigate before answering.</span>
                  </div>
                </div>
                <div className="empty-state-feature">
                  <span className="empty-state-feature-icon"><Icon name="paperclip" size={18} /></span>
                  <div>
                    <strong>Images, documents, video</strong>
                    <span>Attach a file and Zenith routes to whatever model handles it best.</span>
                  </div>
                </div>
                <div className="empty-state-feature">
                  <span className="empty-state-feature-icon"><Icon name="mic" size={18} /></span>
                  <div>
                    <strong>Voice in, voice out</strong>
                    <span>Hold the mic to talk; turn on spoken replies from the header.</span>
                  </div>
                </div>
                <div className="empty-state-feature">
                  <span className="empty-state-feature-icon"><Icon name="command" size={18} /></span>
                  <div>
                    <strong>⌘K for everything</strong>
                    <span>Jump to a conversation, switch persona, or open any setting.</span>
                  </div>
                </div>
              </div>
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              onRetry={handleRetry}
              onRegenerate={handleRegenerate}
              onEdit={handleEdit}
              onApproveTool={handleApproveTool}
              onDenyTool={handleDenyTool}
              onRevertTool={handleRevertTool}
              onPlanDecision={handlePlanDecision}
              siblings={branches[m.parent_id || "root"]}
              onSwitchBranch={handleSwitchBranch}
              onDeleteMessage={handleDeleteMessage}
              onOpenEditor={(text, lang) => setOpenDoc({ text, lang })}
              onRunReverted={() => {
                showToast("Run undone — files restored.", "success");
                selectConversation(activeId);
              }}
              personas={personas}
            />
          ))}
        </div>

        {!isNearBottom && messages.length > 0 && (
          <button className="scroll-to-bottom-btn" onClick={scrollToBottom} title="Scroll to latest">
            <Icon name="chevron-down" size={16} />
          </button>
        )}

        <Composer
          onSend={handleSend}
          onStop={handleStop}
          disabled={!activeId}
          conversationId={activeId}
          agentAvailable={agentAvailable}
          councilAvailable={councilModels.length >= 2}
          imageAvailable={imageAvailable}
          isStreaming={status === "thinking"}
          onError={(msg) => showToast(msg, "error")}
          seedText={seedText}
          installedModels={installedModels}
          continuousVoice={continuousVoice}
          autoListenNonce={autoListenNonce}
          messages={messages}
          contextWindow={contextWindow}
          maxContextMessages={maxContextMessages}
          statusModel={genStats?.model || [...messages].reverse().find((m) => m.model)?.model}
          tokPerSec={genStats?.tokPerSec}
          runFlags={runFlags}
        />
        </div>

        {openDoc && (
          <DocumentEditor
            doc={openDoc}
            onClose={() => setOpenDoc(null)}
            onSendBack={(text) => {
              setSeedText({ text: "```\n" + text + "\n```", nonce: Date.now() });
              setOpenDoc(null);
            }}
          />
        )}
      </main>

      {settingsOpen && (
        <SettingsPanel
          onClose={() => {
            setSettingsOpen(false);
            // Agent/council toggles in the composer depend on config set
            // inside Settings — pick up anything changed this session.
            api.getConfig().then((c) => {
              setAgentAvailable(!!c.agent_enabled);
              setCouncilModels(c.council_models || []);
              setWakeWordEnabled(!!c.wake_word_enabled);
              setWakeWordPhrase(c.wake_word_phrase || "hey zenith");
            }).catch(() => {});
            api.listPersonas().then(setPersonas).catch(() => {});
          }}
          theme={theme}
          onThemeChange={setTheme}
          voiceReplyEnabled={voiceReplyEnabled}
          onVoiceReplyChange={setVoiceReplyEnabled}
          density={density}
          onDensityChange={setDensity}
          ambientAnim={ambientAnim}
          onAmbientChange={setAmbientAnim}
          notificationsEnabled={notificationsEnabled}
          onNotificationsChange={enableNotifications}
          onImported={() => { refreshConversations(); showToast("Import complete — conversations added.", "success"); }}
          onUseSkill={(prompt) => setSeedText({ text: prompt, nonce: Date.now() })}
          initialSection={settingsInitialSection}
          fontScale={fontScale}
          onFontScaleChange={setFontScale}
          highContrast={highContrast}
          onHighContrastChange={setHighContrast}
          reduceMotion={reduceMotion}
          onReduceMotionChange={setReduceMotion}
          dyslexiaFont={dyslexiaFont}
          onDyslexiaFontChange={setDyslexiaFont}
          underlineLinks={underlineLinks}
          onUnderlineLinksChange={setUnderlineLinks}
        />
      )}

      {commandPaletteOpen && (
        <CommandPalette
          open={commandPaletteOpen}
          onClose={() => setCommandPaletteOpen(false)}
          commands={commands}
        />
      )}

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
