import { useEffect, useMemo, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import Composer from "./components/Composer";
import MessageBubble from "./components/MessageBubble";
import SettingsPanel from "./components/SettingsPanel";
import CommandPalette from "./components/CommandPalette";
import ToastStack from "./components/ToastStack";
import Icon from "./components/Icon.jsx";
import LockScreen from "./components/LockScreen.jsx";
import { api } from "./lib/api";

export default function App() {
  const [locked, setLocked] = useState(false);
  const [lockChecked, setLockChecked] = useState(false);
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
  const [activeRole, setActiveRole] = useState("general");
  const [voiceReplyEnabled, setVoiceReplyEnabled] = useState(false);
  const [connectionError, setConnectionError] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("cortex-theme") || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")
  );
  const [density, setDensity] = useState(() => localStorage.getItem("cortex-density") || "comfortable");
  const [accent, setAccent] = useState(() => localStorage.getItem("cortex-accent") || "teal");
  const [notificationsEnabled, setNotificationsEnabled] = useState(
    () => localStorage.getItem("cortex-notifications") === "1"
  );
  const lastRunPollRef = useRef(Date.now() / 1000);
  const [focusMode, setFocusMode] = useState(false);
  const [agentAvailable, setAgentAvailable] = useState(false);
  const [councilModels, setCouncilModels] = useState([]);
  const [personas, setPersonas] = useState([]);
  const [branches, setBranches] = useState({});
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
      new Notification(title, { body, tag: "cortex", icon: "/favicon.ico" });
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
    localStorage.setItem("cortex-notifications", on ? "1" : "0");
  };
  const scrollRef = useRef(null);
  const audioRef = useRef(null);
  const abortRef = useRef(null);
  const titleTimerRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("cortex-theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute("data-density", density);
    localStorage.setItem("cortex-density", density);
  }, [density]);

  useEffect(() => {
    document.documentElement.setAttribute("data-accent", accent);
    localStorage.setItem("cortex-accent", accent);
  }, [accent]);

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
  }, [notificationsEnabled]);

  useEffect(() => {
    api.getConfig().then((c) => {
      setAgentAvailable(!!c.agent_enabled);
      setCouncilModels(c.council_models || []);
    }).catch(() => {});
    api.listPersonas().then(setPersonas).catch(() => {});
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

  const refreshConversations = async () => {
    try {
      const list = await api.listConversations();
      setConversations(list);
    } catch (err) {
      setConnectionError(err.message);
    }
  };

  // Passcode lock: on load, ask the backend whether a lock is set. If it is
  // and we don't already hold a valid unlock token this tab session, show
  // the lock screen before anything else loads.
  useEffect(() => {
    api
      .lockStatus()
      .then(({ enabled }) => {
        setLocked(enabled && !sessionStorage.getItem("cortex-unlock"));
        setLockChecked(true);
      })
      .catch(() => setLockChecked(true));
  }, []);

  useEffect(() => {
    api
      .listConversations()
      .then(async (list) => {
        setConversations(list);
        if (list.length > 0) {
          selectConversation(list[0].id);
        } else {
          const conv = await api.createConversation();
          setConversations([conv]);
          setActiveId(conv.id);
        }
      })
      .catch((err) => setConnectionError(err.message));
  }, []);

  const [isNearBottom, setIsNearBottom] = useState(true);

  useEffect(() => {
    // Don't yank the view back down if the user has deliberately
    // scrolled up to (re)read something while a reply keeps streaming in.
    if (isNearBottom) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
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
      } else if (e.key === "Escape") {
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
  }, [commandPaletteOpen, focusMode]);

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

  const handleCreate = async () => {
    const conv = await api.createConversation();
    setConversations((c) => [conv, ...c]);
    setActiveId(conv.id);
    setMessages([]);
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
      headers: { "Content-Type": "application/json" },
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
      audioRef.current.onended = () => setStatus("idle");
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

  const handleCouncilSend = async (text, attachmentIds) => {
    if (!activeId || councilModels.length < 2) return;
    const userMsg = { id: `local-${Date.now()}`, role: "user", content: text, attachments: [] };
    const assistantMsg = {
      id: `local-assistant-${Date.now()}`,
      role: "assistant",
      content: `Asking ${councilModels.length} models…`,
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
      councilModels.map((m) => `${m}: ${progress[m] || 0} chars`).join(" · ");

    await api.streamCouncil(
      { conversationId: activeId, message: text, attachmentIds, models: councilModels },
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

  const handleSend = async (
    text,
    attachmentIds,
    editContext = null,
    webSearch = false,
    agentMode = false,
    deepResearch = false,
    regenerateOf = null,
    councilMode = false
  ) => {
    if (!activeId) return;
    if (councilMode) return handleCouncilSend(text, attachmentIds);
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
    await api.streamChat(
      { conversationId: activeId, message: text, attachmentIds, webSearch, agentMode, deepResearch, editOf, regenerateOf },
      (event) => {
        if (event.type === "route") {
          setActiveRole(event.role);
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
        } else if (event.type === "token") {
          fullText += event.text;
          setMessages((m) =>
            m.map((msg) => (msg.id === assistantMsg.id ? { ...msg, content: fullText } : msg))
          );
        } else if (event.type === "resumed") {
          showToast("Resuming from where the last run left off…", "info");
        } else if (event.type === "done") {
          setMessages((m) =>
            m.map((msg) => (msg.id === assistantMsg.id ? { ...msg, streaming: false } : msg))
          );
          if (event.checkpointed) {
            showToast("Run paused at the step limit — send a message to continue.", "info", 6000);
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
          notify("Cortex", "Your response is ready.", { onlyWhenHidden: true });
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

  const commands = useMemo(() => {
    const list = [];
    list.push({
      id: "new-chat", group: "Actions", icon: "plus", label: "New chat",
      action: handleCreate,
    });
    list.push({
      id: "toggle-theme", group: "Actions", icon: theme === "dark" ? "sun" : "moon",
      label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
      action: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
    });
    list.push({
      id: "toggle-sidebar", group: "Actions", icon: "panel-left",
      label: sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar",
      action: () => setSidebarCollapsed((v) => !v),
    });
    list.push({
      id: "toggle-voice", group: "Actions", icon: "volume-2",
      label: voiceReplyEnabled ? "Turn off spoken replies" : "Turn on spoken replies",
      action: () => setVoiceReplyEnabled((v) => !v),
    });
    list.push({
      id: "toggle-focus", group: "Actions", icon: "target",
      label: focusMode ? "Exit focus mode" : "Enter focus mode",
      hint: "⌘.",
      action: () => setFocusMode((v) => !v),
    });
    list.push({
      id: "toggle-density", group: "Actions", icon: "menu",
      label: density === "compact" ? "Switch to comfortable density" : "Switch to compact density",
      action: () => setDensity((d) => (d === "compact" ? "comfortable" : "compact")),
    });
    if (agentAvailable) {
      list.push({
        id: "set-workdir", group: "Actions", icon: "folder",
        label: activeConversation?.workdir ? "Change working directory" : "Set working directory",
        action: handleSetWorkdir,
      });
    }
    for (const s of [
      { id: "appearance", label: "Appearance" },
      { id: "memory", label: "Memory & persona" },
      { id: "personas", label: "Personas" },
      { id: "agent", label: "Agent tools" },
      { id: "council", label: "Council" },
      { id: "routing", label: "Model routing" },
      { id: "folders", label: "Folders" },
      { id: "schedules", label: "Schedules" },
      { id: "data", label: "Data" },
    ]) {
      list.push({
        id: `settings-${s.id}`, group: "Settings", icon: "settings",
        label: `Settings — ${s.label}`,
        action: () => openSettingsAt(s.id),
      });
    }
    for (const p of personas) {
      list.push({
        id: `persona-${p.id}`, group: "Personas", icon: "masks",
        label: `Switch to persona: ${p.name}`,
        hint: activeConversation?.persona_id === p.id ? "current" : undefined,
        action: () => handlePersonaChange(p.id),
      });
    }
    if (activeConversation?.persona_id) {
      list.push({
        id: "persona-none", group: "Personas", icon: "x", label: "Remove persona from this conversation",
        action: () => handlePersonaChange(null),
      });
    }
    for (const c of conversations) {
      list.push({
        id: `conv-${c.id}`, group: "Conversations", icon: "message-circle", label: c.title,
        action: () => selectConversation(c.id),
      });
    }
    return list;
  }, [conversations, personas, activeConversation, theme, sidebarCollapsed, voiceReplyEnabled, focusMode, density]);

  if (!lockChecked) return null; // avoid a flash of the app before we know
  if (locked) return <LockScreen onUnlocked={() => window.location.reload()} />;

  return (
    <div className={`app-shell ${focusMode ? "app-shell-focus" : ""}`}>
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
        />
      )}

      {!focusMode && !sidebarCollapsed && (
        <div
          className="sidebar-backdrop"
          onClick={() => setSidebarCollapsed(true)}
          aria-hidden="true"
        />
      )}

      <main className="chat-main">
        <header className="chat-header">
          <button
            className="mobile-menu-btn"
            onClick={() => setSidebarCollapsed((v) => !v)}
            title="Toggle sidebar"
          >
            <Icon name="menu" size={18} />
          </button>
          <h1>{activeConversation?.title || "Cortex"}</h1>
          <div className="header-actions">
            <button
              className={`icon-btn focus-toggle-btn ${focusMode ? "is-active" : ""}`}
              onClick={() => setFocusMode((v) => !v)}
              title={focusMode ? "Exit focus mode (⌘. or Esc)" : "Focus mode — hide sidebar and chrome (⌘.)"}
            >
              <Icon name="target" size={16} />
            </button>
            {!focusMode && agentAvailable && (
              <button
                className={`workdir-btn ${activeConversation?.workdir ? "is-active" : ""}`}
                onClick={handleSetWorkdir}
                title={
                  activeConversation?.workdir
                    ? `Working directory: ${activeConversation.workdir} — click to change`
                    : "Set a working directory for agent mode (bash cwd + relative paths)"
                }
              >
                <Icon name="folder" size={14} /> {activeConversation?.workdir ? activeConversation.workdir.split("/").pop() : "Set folder"}
              </button>
            )}
            {!focusMode && personas.length > 0 && (
              <select
                className="persona-picker"
                value={activeConversation?.persona_id || ""}
                onChange={(e) => handlePersonaChange(e.target.value || null)}
                title="Persona for this conversation"
              >
                <option value="">No persona</option>
                {personas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.icon ? `${p.icon} ` : ""}
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            {!focusMode && (
              <button
                className={`theme-toggle ${theme === "light" ? "theme-toggle-light" : ""}`}
                onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
                title="Toggle theme"
                role="switch"
                aria-checked={theme === "light"}
              >
                <span className="theme-toggle-track">
                  <span className="theme-toggle-thumb">
                    <Icon name={theme === "dark" ? "moon" : "sun"} size={12} />
                  </span>
                </span>
              </button>
            )}
            {!focusMode && (
              <button
                className={`voice-toggle ${voiceReplyEnabled ? "voice-toggle-on" : ""}`}
                onClick={() => setVoiceReplyEnabled((v) => !v)}
                title="Speak replies aloud"
              >
                <Icon name={voiceReplyEnabled ? "volume-2" : "volume-x"} size={14} /> {voiceReplyEnabled ? "Voice on" : "Voice off"}
              </button>
            )}
          </div>
        </header>

        {connectionError && (
          <div className="banner-error">
            {connectionError}
            <button onClick={() => setSettingsOpen(true)}>Open settings</button>
          </div>
        )}

        <div className="chat-scroll" ref={scrollRef} onScroll={handleChatScroll}>
          {messages.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-mark" />
              <h2>Everything runs on your machine.</h2>
              <p>
                Type, drop an image, upload a document, or hold the mic — Cortex reads
                what's installed on your Ollama and routes the turn automatically.
              </p>
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
                    <span>Attach a file and Cortex routes to whatever model handles it best.</span>
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
          isStreaming={status === "thinking"}
          onError={(msg) => showToast(msg, "error")}
        />
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
            }).catch(() => {});
            api.listPersonas().then(setPersonas).catch(() => {});
          }}
          theme={theme}
          onThemeChange={setTheme}
          voiceReplyEnabled={voiceReplyEnabled}
          onVoiceReplyChange={setVoiceReplyEnabled}
          density={density}
          onDensityChange={setDensity}
          accent={accent}
          onAccentChange={setAccent}
          notificationsEnabled={notificationsEnabled}
          onNotificationsChange={enableNotifications}
          onImported={() => { refreshConversations(); showToast("Import complete — conversations added.", "success"); }}
          initialSection={settingsInitialSection}
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