import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

/** An optional "Get started" card on the home screen: a readiness check
 * with copyable fixes when something's missing, and a few next steps that
 * tick themselves off as you use Zenith. Skip it for now or hide it for
 * good — nothing here is required before chatting. */
export default function GetStarted({ onOpenSettings, onOpenCode, onOpenTour, onFocusComposer }) {
  const [data, setData] = useState(null);
  const [skipped, setSkipped] = useState(() => {
    try { return sessionStorage.getItem("zenith-getstarted-skip") === "1"; } catch { return false; }
  });
  const [copied, setCopied] = useState("");

  useEffect(() => {
    if (skipped) return;
    let alive = true;
    const load = () => api.setupStatus().then((d) => alive && setData(d)).catch(() => {});
    load();
    const t = setInterval(load, 20000);
    return () => { alive = false; clearInterval(t); };
  }, [skipped]);

  if (skipped || !data || data.hidden) return null;
  let themed = false;
  try { themed = !!localStorage.getItem("zenith-theme"); } catch { /* ignore */ }
  const p = data.progress;
  const steps = [
    { id: "model", done: data.ready_to_chat, title: "Have a model to chat with", text: "A local model from Ollama, or an API provider.",
      action: ["Browse models", () => onOpenSettings("models")], alt: ["Add a provider", () => onOpenSettings("providers")] },
    { id: "chat", done: p.chatted, title: "Send a first message", text: "Ask anything — Zenith picks a fitting model.", action: ["Start typing", onFocusComposer] },
    { id: "file", done: p.file, title: "Try a file", text: "Paste an image or drop a PDF into the message box." },
    { id: "deeper", done: p.research || p.agent, title: "Try Deep Research or Code", text: "A sourced report, or an editor with an agent beside the chat.",
      action: ["Open Code", onOpenCode] },
    { id: "yours", done: themed || p.memory, title: "Make it yours", text: "A theme, a persona, or a fact for it to remember.", action: ["Appearance", () => onOpenSettings("appearance")] },
  ];
  const left = steps.filter((s) => !s.done).length;
  if (left === 0) return null;
  const problems = data.checks.filter((c) => !c.ok && !(c.optional && data.ready_to_chat));
  const copy = async (text) => { try { await navigator.clipboard.writeText(text); setCopied(text); setTimeout(() => setCopied(""), 1500); } catch { /* ignore */ } };
  const skip = () => { try { sessionStorage.setItem("zenith-getstarted-skip", "1"); } catch { /* ignore */ } setSkipped(true); };
  const hide = async () => { await api.patchConfig({ setup_checklist_hidden: true }).catch(() => {}); setSkipped(true); };

  return (
    <section className="getstarted" aria-label="Get started">
      <header>
        <div>
          <strong>Get started</strong>
          <span>{data.ready_to_chat ? `${steps.length - left} of ${steps.length} done — all optional` : "One thing to sort out before chatting"}</span>
        </div>
        <div className="getstarted-links">
          <button onClick={onOpenTour}>Tour</button>
          <button onClick={skip}>Skip for now</button>
          <button onClick={hide}>Don't show again</button>
        </div>
      </header>
      {problems.length > 0 && (
        <ul className="getstarted-checks">
          {problems.map((c) => (
            <li key={c.id}>
              <Icon name="alert-triangle" size={13} />
              <span><b>{c.label}:</b> {c.detail}{c.why && <em>{c.why}</em>}
                {c.fix && (
                  <span className="getstarted-fix">
                    <code>{c.fix}</code>
                    <button onClick={() => copy(c.fix)} aria-label="Copy">{copied === c.fix ? <Icon name="check" size={12} /> : <Icon name="copy" size={12} />}</button>
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <ol className="getstarted-steps">
        {steps.map((s) => (
          <li key={s.id} className={s.done ? "is-done" : ""}>
            <span className="getstarted-tick">{s.done ? <Icon name="check" size={12} /> : null}</span>
            <span className="getstarted-text"><b>{s.title}</b><em>{s.text}</em></span>
            {!s.done && s.action && <button className="wf-btn" onClick={s.action[1]}>{s.action[0]}</button>}
            {!s.done && s.alt && <button className="wf-btn" onClick={s.alt[1]}>{s.alt[0]}</button>}
          </li>
        ))}
      </ol>
    </section>
  );
}
