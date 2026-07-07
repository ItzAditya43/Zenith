import { useEffect, useMemo, useRef, useState } from "react";
import AmbientField from "./components/AmbientField";
import Sidebar from "./components/Sidebar";
import Composer from "./components/Composer";
import MessageBubble from "./components/MessageBubble";
import SettingsPanel from "./components/SettingsPanel";
import { api } from "./lib/api";

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
  const scrollRef = useRef(null);
  const audioRef = useRef(null);
  const abortRef = useRef(null);

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

  const selectConversation = async (id) => {
    setActiveId(id);
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

  const handleSend = async (text, attachmentIds) => {
    if (!activeId) return;
    const userMsg = { id: `local-${Date.now()}`, role: "user", content: text, attachments: [] };
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

    let fullText = "";
    await api.streamChat(
      { conversationId: activeId, message: text, attachmentIds },
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

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeId),
    [conversations, activeId]
  );

  return (
    <div className="app-shell">
      <AmbientField status={status} role={activeRole} />
      <audio ref={audioRef} hidden />

      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={selectConversation}
        onCreate={handleCreate}
        onDelete={handleDelete}
        onOpenSettings={() => setSettingsOpen(true)}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
      />

      <main className="chat-main">
        <header className="chat-header">
          <h1>{activeConversation?.title || "Cortex"}</h1>
          <button
            className={`voice-toggle ${voiceReplyEnabled ? "voice-toggle-on" : ""}`}
            onClick={() => setVoiceReplyEnabled((v) => !v)}
            title="Speak replies aloud"
          >
            {voiceReplyEnabled ? "🔊 Voice on" : "🔈 Voice off"}
          </button>
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
            <MessageBubble key={m.id} message={m} onRetry={handleRetry} />
          ))}
        </div>

        <Composer
          onSend={handleSend}
          onStop={handleStop}
          disabled={!activeId}
          conversationId={activeId}
          isStreaming={status === "thinking"}
        />
      </main>

      {settingsOpen && <SettingsPanel onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}