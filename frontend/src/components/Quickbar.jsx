import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

const CONV_KEY = "zenith-quickbar-conversation";

function summarize(tool, args) {
  const a = args || {};
  const v = a.text ?? a.keys ?? a.target ?? a.window ?? a.query ?? a.question ?? a.workspace ?? a.command ?? a.path ?? a.url ?? "";
  return typeof v === "string" ? v : JSON.stringify(v);
}

const LABEL = {
  desktop_windows: "Look at open windows", desktop_focus: "Focus window", desktop_open: "Open",
  desktop_workspace: "Switch workspace", desktop_move_window: "Move window", desktop_type: "Type",
  desktop_keys: "Press keys", desktop_screen: "Look at the screen", desktop_find: "Find on screen",
  desktop_click: "Click target",
};

async function hideBar() {
  try {
    await api.hideQuickbar();
    return;
  } catch {
    /* not on Hyprland: fall back to hiding the window */
  }
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().hide();
  } catch {
    /* running in a browser tab: nothing to hide */
  }
}

/**
 * The desktop popout (Super+Space). Type what you want done; the agent works
 * through your desktop with the desktop_* tools and every action waits for
 * Approve here (unless you've set agent mode to full-auto).
 */
export default function Quickbar() {
  const [text, setText] = useState("");
  const [steps, setSteps] = useState([]); // {id, tool, args, status, result}
  const [answer, setAnswer] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [cfg, setCfg] = useState(null);
  const input = useRef(null);
  const abort = useRef(null);
  const convId = useRef(null);

  useEffect(() => {
    api.getConfig().then(setCfg).catch(() => {});
    document.documentElement.classList.add("quickbar-root");
    // Same theme as the main window (it shares this origin's storage).
    try {
      document.documentElement.setAttribute("data-theme", localStorage.getItem("zenith-theme") || "oled-ember");
    } catch {
      document.documentElement.setAttribute("data-theme", "oled-ember");
    }
    const focus = () => setTimeout(() => input.current?.focus(), 30);
    focus();
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, []);

  const ensureConversation = async () => {
    if (convId.current) return convId.current;
    let id = null;
    try {
      id = localStorage.getItem(CONV_KEY);
    } catch {
      /* storage blocked */
    }
    if (id) {
      try {
        await api.getMessages(id);
      } catch {
        id = null;
      }
    }
    if (!id) {
      const c = await api.createConversation("Desktop assistant");
      id = c.id;
      try {
        localStorage.setItem(CONV_KEY, id);
      } catch {
        /* storage blocked */
      }
    }
    convId.current = id;
    return id;
  };

  const enable = async () => {
    setCfg(await api.patchConfig({ agent_enabled: true, desktop_control_enabled: true }));
  };

  const send = async () => {
    const msg = text.trim();
    if (!msg || running) return;
    setError(null);
    setSteps([]);
    setAnswer("");
    setRunning(true);
    const controller = new AbortController();
    abort.current = controller;
    try {
      const conversationId = await ensureConversation();
      setText("");
      await api.streamChat(
        { conversationId, message: msg, attachmentIds: [], agentMode: true },
        (ev) => {
          if (ev.type === "tool_call" || ev.type === "tool_pending") {
            setSteps((s) => {
              const rest = s.filter((x) => x.id !== ev.id);
              return [...rest, { id: ev.id, tool: ev.tool, args: ev.args, status: ev.type === "tool_pending" ? "pending" : "running" }];
            });
          } else if (ev.type === "tool_result") {
            setSteps((s) => s.map((x) => (x.id === ev.id ? { ...x, status: "done", result: ev.result } : x)));
          } else if (ev.type === "tool_denied") {
            setSteps((s) => s.map((x) => (x.id === ev.id ? { ...x, status: "denied" } : x)));
          } else if (ev.type === "token") {
            setAnswer((a) => a + (ev.text || ""));
          } else if (ev.type === "error") {
            setError(ev.message || "Something went wrong.");
          }
        },
        controller.signal,
      );
    } catch (err) {
      if (err.name !== "AbortError") setError(err.message);
    } finally {
      setRunning(false);
      abort.current = null;
      setTimeout(() => input.current?.focus(), 30);
    }
  };

  const decide = async (step, ok) => {
    setSteps((s) => s.map((x) => (x.id === step.id ? { ...x, status: ok ? "running" : "denied" } : x)));
    try {
      if (ok) await api.approveToolCall(step.id);
      else await api.denyToolCall(step.id);
    } catch (err) {
      setError(err.message);
    }
  };

  const pending = steps.find((s) => s.status === "pending");

  const onKey = (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      if (running) {
        abort.current?.abort();
        if (pending) decide(pending, false);
      } else {
        hideBar();
      }
    } else if (pending && !text && (e.key === "y" || e.key === "n")) {
      e.preventDefault();
      decide(pending, e.key === "y");
    }
  };

  const off = cfg && (!cfg.agent_enabled || !cfg.desktop_control_enabled);

  return (
    <div className="qb" onKeyDown={onKey}>
      <form className="qb-bar" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <img className="qb-mark" src="/favicon.svg" alt="" aria-hidden="true" />
        <input
          ref={input}
          className="qb-input"
          placeholder={running ? "Working… Esc to stop" : "Tell Zenith what to do on your desktop"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={running}
          aria-label="What should Zenith do?"
        />
        {running ? (
          <button type="button" className="qb-stop" onClick={() => abort.current?.abort()} aria-label="Stop">
            <span className="stop-glyph" aria-hidden="true" />
          </button>
        ) : (
          <kbd className="keycap">↵</kbd>
        )}
      </form>

      {off && (
        <div className="qb-note">
          <span>Desktop control is off. When on, Zenith can open apps, type, press keys and click — every action asks you first.</span>
          <button className="settings-btn-primary" onClick={enable}>Turn on</button>
        </div>
      )}

      {(steps.length > 0 || answer || error) && (
        <div className="qb-body">
          {steps.map((s) => (
            <div key={s.id} className={`qb-step is-${s.status}`}>
              <span className="qb-step-icon" aria-hidden="true">
                {s.status === "done" ? <Icon name="check" size={12} /> : s.status === "denied" ? <Icon name="x" size={12} /> : s.status === "pending" ? "?" : <span className="attach-spinner" />}
              </span>
              <span className="qb-step-text">
                <strong>{LABEL[s.tool] || s.tool}</strong> {summarize(s.tool, s.args) && <span className="qb-arg">{summarize(s.tool, s.args).slice(0, 120)}</span>}
                {s.status === "done" && s.result && <span className="qb-result">{String(s.result).split("\n")[0].slice(0, 140)}</span>}
              </span>
              {s.status === "pending" && (
                <span className="qb-actions">
                  <button className="settings-btn-primary" onClick={() => decide(s, true)}>Approve <kbd className="keycap">y</kbd></button>
                  <button className="settings-btn-secondary" onClick={() => decide(s, false)}>Deny <kbd className="keycap">n</kbd></button>
                </span>
              )}
            </div>
          ))}
          {answer && <p className="qb-answer">{answer}</p>}
          {error && <p className="qb-error" role="alert">{error}</p>}
        </div>
      )}
      <footer className="qb-foot">
        <span>Esc {running ? "stops" : "closes"}</span>
        <span>Every action asks first · password managers are never touched</span>
      </footer>
    </div>
  );
}
