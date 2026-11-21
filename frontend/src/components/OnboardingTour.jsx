import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

/**
 * First-run onboarding: a short guided tour of everything Zenith does, with
 * buttons that take you straight to each feature. Shown once (localStorage
 * "zenith-onboarded"); replay from the command palette ("Show onboarding").
 */

function Welcome({ go }) {
  return (
    <div className="ob-hero">
      <div className="hero-orb" aria-hidden="true"><span /></div>
      <span className="empty-kicker">Welcome to</span>
      <h2>Zenith</h2>
      <p>
        A private AI workspace on your own computer: chat, code, research, documents, memory,
        voice and desktop control — with your local models, and API models when you want them.
      </p>
      <button className="ob-primary" onClick={go}>Take the tour <Icon name="chevron-right" size={14} /></button>
    </div>
  );
}

function Models({ openSettings }) {
  const [state, setState] = useState(null);
  useEffect(() => {
    Promise.all([api.listModels(true).catch(() => []), api.ollamaAccount().catch(() => null)])
      .then(([models, acct]) => setState({ count: models.length, local: models.filter((m) => !m.cloud).length, acct }));
  }, []);
  return (
    <>
      <p className="ob-lead">Zenith runs on models. Start with what's on this machine; add more any time.</p>
      <div className="ob-status">
        {state == null ? (
          <span>Checking Ollama…</span>
        ) : state.count > 0 ? (
          <span><span className="dc-dot is-ok" /> Ollama is connected · {state.local} local model{state.local === 1 ? "" : "s"}{state.count > state.local ? ` · ${state.count - state.local} cloud` : ""}</span>
        ) : (
          <span><span className="dc-dot" /> No models found. Install Ollama from ollama.com, then download a model below.</span>
        )}
        {state?.acct?.signed_in && <span className="ob-sub">Signed in to Ollama as {state.acct.name} ({state.acct.plan} plan)</span>}
      </div>
      <div className="ob-actions">
        <button className="ob-card-btn" onClick={() => openSettings("models")}>
          <Icon name="download" size={15} /><strong>Browse the model library</strong><span>Download a size that fits your GPU, with one click.</span>
        </button>
        <button className="ob-card-btn" onClick={() => openSettings("providers")}>
          <Icon name="cloud" size={15} /><strong>Add an API provider</strong><span>OpenAI, Claude, Gemini, OpenRouter, Groq… or LM Studio.</span>
        </button>
        <button className="ob-card-btn" onClick={() => openSettings("routing")}>
          <Icon name="target" size={15} /><strong>Model routing</strong><span>Zenith picks a model per message; pin your favourites per role.</span>
        </button>
      </div>
    </>
  );
}

const STEPS = [
  { id: "welcome", title: "", render: (p) => <Welcome go={p.next} /> },
  { id: "models", icon: "grid", title: "Your models", render: (p) => <Models openSettings={p.openSettings} /> },
  {
    id: "chat", icon: "message-circle", title: "Chat that does more",
    points: [
      ["Modes", "The pill next to + switches between Just chat, Web search, Deep Research, Agent, Council (several models at once) and Compare."],
      ["Paste anything", "Ctrl+V an image or screenshot, drop files, or attach documents — Zenith reads PDFs, images and code."],
      ["Slash commands", "Type / for shortcuts: /research, /agent, /search, /image, /council."],
      ["Voice", "Hold the mic to talk; the headphones in the header start hands-free voice mode."],
      ["Branches", "Edit or regenerate any message and switch between versions without losing either."],
    ],
  },
  {
    id: "code", icon: "terminal", title: "Code with an editor beside the chat",
    points: [
      ["Code", "Pick Code in the sidebar, choose a project folder, and you get files, an editor and a terminal next to the chat."],
      ["Agent mode", "The agent reads, edits and runs your project. Every change shows as a diff and waits for your approval; undo is one click."],
      ["Git built in", "The Changes tab stages, commits, branches and pushes. With the GitHub CLI: issues, pull requests, and 'work on this issue'."],
      ["Edit a selection", "Select code and describe a change — the rewrite comes back as a diff to apply."],
      ["Separate copies", "Let the agent try something on its own branch and folder without touching your checkout."],
    ],
    action: ["Open Code", (p) => p.openCode()],
  },
  {
    id: "desktop", icon: "bot", title: "Control your desktop",
    points: [
      ["Super+Space", "A popout appears anywhere. Tell Zenith what to do: open an app, switch windows, type, press shortcuts, click a button by name."],
      ["You stay in charge", "It looks freely but asks before every action. It never types into a password manager."],
      ["Off by default", "Turn it on in Settings → Agent tools → Desktop control, along with App accessibility for clicking by name."],
    ],
    action: ["Desktop control settings", (p) => p.openSettings("agent")],
  },
  {
    id: "knowledge", icon: "flask", title: "Research, documents and memory",
    points: [
      ["Deep Research", "Multi-step searching and reading, written up as a report with sources you can reopen."],
      ["Your documents", "Upload files or watch folders; answers cite the passages they used."],
      ["Memory", "Zenith remembers durable facts about you between chats — you can review or forget any of them."],
      ["Personal tools", "Notes, to-dos, a calendar, email, schedules and automations — all local."],
    ],
    action: ["Memory & persona settings", (p) => p.openSettings("memory")],
  },
  {
    id: "privacy", icon: "settings", title: "Private by default, yours to shape",
    points: [
      ["Local first", "Everything runs on this machine. Web search, API providers and cloud models are the only things that leave it, and only when you use them."],
      ["Lock and sandbox", "Set a passcode in Settings → Data; run agent commands in a sandbox (Bubblewrap or Docker)."],
      ["Make it yours", "Nine themes, accessibility options, personas and per-project instructions."],
      ["Find anything", "⌘K opens the command palette; j / k move between chats; ? shows every shortcut."],
    ],
  },
];

export default function OnboardingTour({ onClose, onOpenSettings, onOpenCode }) {
  const [i, setI] = useState(0);
  const step = STEPS[i];
  const last = i === STEPS.length - 1;
  const next = () => (last ? onClose() : setI(i + 1));
  const back = () => setI(Math.max(0, i - 1));
  const finishThen = (fn) => () => {
    onClose();
    setTimeout(fn, 50);
  };
  const props = {
    next,
    openSettings: (section) => finishThen(() => onOpenSettings?.(section))(),
    openCode: () => finishThen(() => onOpenCode?.())(),
  };

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="ob-overlay" role="dialog" aria-modal="true" aria-label="Welcome to Zenith">
      <div className={`ob-panel ${i === 0 ? "is-welcome" : ""}`}>
        <button className="ob-skip" onClick={onClose}>Skip</button>
        <div className="ob-body" key={step.id}>
          {step.render ? (
            <>
              {step.title && (
                <header className="ob-head">
                  <span className="ob-icon"><Icon name={step.icon} size={18} /></span>
                  <h2>{step.title}</h2>
                </header>
              )}
              {step.render(props)}
            </>
          ) : (
            <>
              <header className="ob-head">
                <span className="ob-icon"><Icon name={step.icon} size={18} /></span>
                <h2>{step.title}</h2>
              </header>
              <ul className="ob-points">
                {step.points.map(([t, d]) => (
                  <li key={t}><strong>{t}</strong><span>{d}</span></li>
                ))}
              </ul>
              {step.action && (
                <button className="ob-secondary" onClick={() => step.action[1](props)}>
                  {step.action[0]} <Icon name="chevron-right" size={13} />
                </button>
              )}
            </>
          )}
        </div>
        {i > 0 && (
          <footer className="ob-foot">
            <div className="ob-dots" aria-label={`Step ${i} of ${STEPS.length - 1}`}>
              {STEPS.slice(1).map((s, k) => (
                <button key={s.id} className={`ob-dot ${k + 1 === i ? "is-on" : ""}`} onClick={() => setI(k + 1)} aria-label={`Go to ${s.title}`} />
              ))}
            </div>
            <div className="ob-nav">
              <button className="ob-ghost" onClick={back}>Back</button>
              <button className="ob-primary" onClick={next}>{last ? "Start using Zenith" : "Next"}</button>
            </div>
          </footer>
        )}
      </div>
    </div>
  );
}
