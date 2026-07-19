import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import Composer from "./components/Composer";
import MessageBubble from "./components/MessageBubble";
import SettingsPanel from "./components/SettingsPanel";
import { api } from "./lib/api";

// Tier 6 #13 — three.js is heavy; load the ambient background lazily.
const AmbientField = lazy(() => import("./components/AmbientField"));

export default function App() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
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
  const [agentAvailable, setAgentAvailable] = useState(false);
  const scrollRef = useRef(null);
  const audioRef = useRef(null);
  const abortRef = useRef(null);
  const titleTimerRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("cortex-theme", theme);
  }, [theme]);

  useEffect(() => {
    api.getConfig().then((c) => setAgentAvailable(!!c.agent_enabled)).catch(() => {});
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

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Keyboard shortcuts (Tier 6 #6) — skip when typing in inputs
  useEffect(() => {
    const handler = (e) => {
      const tag = e.target.tagName;
      const isInput = tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable;
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        if (isInput) return; // let native Cmd+K (e.g. in sidebar search) pass through
        e.preventDefault();
        document.getElementById("sidebar-search")?.focus();
      } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        // Send is handled in Composer; this is a no-op placeholder for focus.
      } else if (e.key === "Escape") {
        if (isInput) return; // let inputs handle Escape themselves (blur, etc.)
        setSettingsOpen(false);
        setSearchResults(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const selectConversation = async (id) => {
    setActiveId(id);
    setSearchResults(null);
    const msgs = await api.getMessages(id);
    setMessages(msgs);
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

  const maybeGenerateTitle = (convId, firstUserText) => {
    // Tier 6 #4 — auto-title after first user message.
    if (titleTimerRef.current) clearTimeout(titleTimerRef.current);
    titleTimerRef.current = setTimeout(async () => {
      try {
        const { title } = await api.setTitle(convId, firstUserText);
        if (title) {
          setConversations((cs) => cs.map((c) => (c.id === convId ? { ...c, title } : c)));
        }
      } catch {
        /* title is best-effort */
      }
    }, 1200);
  };

  const handleSend = async (text, attachmentIds, editContext = null, webSearch = false, agentMode = false) => {
    if (!activeId) return;
    let history = messages;
    if (editContext) {
      // Drop the edited user message + everything after it, then re-send.
      const idx = messages.findIndex((m) => m.id === editContext.messageId);
      history = messages.slice(0, idx);
      setMessages(history);
    }
    const userMsg = {
      id: `local-${Date.now()}`,
      role: "user",
      content: text,
      attachments: [],
    };
    const assistantMsg = {
      id: `local-assistant-${Date.now()}`,
      role: "assistant",
      content: "",
      streaming: true,
      model: null,
      route_role: null,
    };
    setMessages((m) => [...m, userMsg, assistantMsg]);
    setStatus("thinking");
    setConnectionError(null);

    // Cancel any in-flight stream before starting a new one (Tier 1 #7).
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Auto-title on first user message of a fresh conversation.
    const conv = conversations.find((c) => c.id === activeId);
    if (conv && (conv.title === "New chat" || !conv.title)) {
      maybeGenerateTitle(activeId, text);
    }

    let fullText = "";
    await api.streamChat(
      { conversationId: activeId, message: text, attachmentIds, webSearch, agentMode },
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
        } else if (event.type === "tool_call") {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === assistantMsg.id
                ? {
                    ...msg,
                    toolCalls: [
                      ...(msg.toolCalls || []),
                      { id: event.id, tool: event.tool, args: event.args, risk: event.risk, status: "running" },
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
        } else if (event.type === "token") {
          fullText += event.text;
          setMessages((m) =>
            m.map((msg) => (msg.id === assistantMsg.id ? { ...msg, content: fullText } : msg))
          );
        } else if (event.type === "done") {
          setMessages((m) =>
            m.map((msg) => (msg.id === assistantMsg.id ? { ...msg, streaming: false } : msg))
          );
          setConversations((cs) =>
            cs.map((c) => (c.id === activeId ? { ...c, updated_at: Date.now() / 1000 } : c))
          );
          if (voiceReplyEnabled && fullText.trim()) {
            playReply(fullText);
          } else {
            setStatus("idle");
          }
          // Tier 6 #15 — notify when tab is backgrounded.
          if (document.hidden && "Notification" in window && Notification.permission === "granted") {
            new Notification("Cortex", { body: "Response ready" });
          }
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
                    content: msg.content || `⚠ ${event.message}`,
                  }
                : msg
            )
          );
        }
      },
      controller.signal
    );
    if (abortRef.current === controller) abortRef.current = null;
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
    // Regenerate the assistant response for the user turn before it.
    const idx = messages.findIndex((m) => m.id === msg.id);
    if (idx < 0) return;
    let userText = "";
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (messages[i].role === "user") {
        userText = messages[i].content;
        break;
      }
    }
    if (!userText) return;
    setMessages((m) => m.filter((mm) => mm.id !== msg.id));
    await handleSend(userText, []);
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
      const results = await api.searchConversations(q);
      setSearchResults(results);
    } catch {
      setSearchResults([]);
    }
  };

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeId),
    [conversations, activeId]
  );

  return (
    <div className="app-shell">
      <Suspense fallback={null}>
        <AmbientField status={status} role={activeRole} theme={theme} />
      </Suspense>

      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={selectConversation}
        onCreate={handleCreate}
        onDelete={handleDelete}
        onOpenSettings={() => setSettingsOpen(true)}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        searchQuery={searchQuery}
        onSearch={runSearch}
        searchResults={searchResults}
      />

      <main className="chat-main">
        <header className="chat-header">
          <button
            className="mobile-menu-btn"
            onClick={() => setSidebarCollapsed((v) => !v)}
            title="Toggle sidebar"
          >
            ☰
          </button>
          <h1>{activeConversation?.title || "Cortex"}</h1>
          <div className="header-actions">
            <button
              className={`theme-toggle ${theme === "light" ? "theme-toggle-light" : ""}`}
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              title="Toggle theme"
              role="switch"
              aria-checked={theme === "light"}
            >
              <span className="theme-toggle-track">
                <span className="theme-toggle-thumb">
                  {theme === "dark" ? "🌙" : "☀️"}
                </span>
              </span>
            </button>
            <button
              className={`voice-toggle ${voiceReplyEnabled ? "voice-toggle-on" : ""}`}
              onClick={() => setVoiceReplyEnabled((v) => !v)}
              title="Speak replies aloud"
            >
              {voiceReplyEnabled ? "🔊 Voice on" : "🔈 Voice off"}
            </button>
          </div>
        </header>

        {connectionError && (
          <div className="banner-error">
            {connectionError}
            <button onClick={() => setSettingsOpen(true)}>Open settings</button>
          </div>
        )}

        <div className="chat-scroll" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-mark" />
              <h2>Everything runs on your machine.</h2>
              <p>
                Type, drop an image, upload a document, or hold the mic — Cortex reads
                what's installed on your Ollama and routes the turn automatically.
              </p>
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
            />
          ))}
        </div>

        <Composer
          onSend={handleSend}
          onStop={handleStop}
          disabled={!activeId}
          conversationId={activeId}
          agentAvailable={agentAvailable}
          isStreaming={status === "thinking"}
        />
      </main>

      {settingsOpen && (
        <SettingsPanel
          onClose={() => setSettingsOpen(false)}
          theme={theme}
          onThemeChange={setTheme}
          voiceReplyEnabled={voiceReplyEnabled}
          onVoiceReplyChange={setVoiceReplyEnabled}
        />
      )}
    </div>
  );
}