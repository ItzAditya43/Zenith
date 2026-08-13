import { useState } from "react";
import Icon from "./Icon.jsx";

const PROFILES = [
  {
    id: "private-chat",
    label: "Private ChatGPT replacement",
    picks: [
      "Chat & multimodal — works the moment you install, no setup",
      "Voice in & out — talk instead of type, hear replies back",
      "Long-term memory — it remembers who you are between chats",
      "Image generation — pictures, without a separate app",
    ],
  },
  {
    id: "developer",
    label: "Developer",
    picks: [
      "Agent mode — shell + file edits + git, with an approval gate",
      "Code editor + git — file tree and diffs scoped to your working directory",
      "MCP tool servers — bring in tools Zenith doesn't ship natively",
      "Deep research — cited answers for API/library lookups",
    ],
  },
  {
    id: "writer-researcher",
    label: "Writer / researcher / student",
    picks: [
      "Deep research — a cited, reopenable report",
      "Document RAG — upload PDFs/papers and ask questions grounded in them",
      "Long-term memory — keeps facts about an ongoing project straight",
      "Conversation branching — explore an alternate draft safely",
    ],
  },
  {
    id: "privacy-first",
    label: "Privacy-conscious first",
    picks: [
      "Passcode lock & encryption — API-level lock, AES-256-GCM at rest",
      "Single-user, no telemetry — no account, no analytics",
      "Know the exceptions — web search, URL reading, and optional Ollama Cloud are the only opt-in features that leave your machine",
    ],
  },
  {
    id: "tinkerer",
    label: "Tinkerer / self-hoster",
    picks: [
      "Automation & webhooks — trigger → action rules on real events",
      "MCP tool servers — connect anything speaking Model Context Protocol",
      "Folder watching & scheduled turns — react to files, run recurring prompts",
      "Desktop app + multi-device sync — tray on one machine, paired access elsewhere",
    ],
  },
];

const HIGHLIGHTS = [
  { icon: "bot", title: "Agent mode", desc: "Let the model run shell commands, edit files, and use git — turn it on in Settings → Agent tools. Notes and to-dos are already answerable in plain chat, no setup needed." },
  { icon: "clock", title: "Calendar, notes, to-dos", desc: "Header icons next to the theme picker — a local Keep/Calendar/To-do suite (with a drag-and-drop board view), no account needed." },
  { icon: "flask", title: "Deep research", desc: "Ask for a research-style answer and it saves as a reopenable report you can ask follow-ups against." },
  { icon: "terminal", title: "Code editor + git", desc: "Bind a working directory (folder icon in the header) to get a file tree, editor, git status/diff, and one-click extraction of a conversation's code into real files." },
  { icon: "share", title: "Knowledge graph + automation", desc: "See how your conversations, memories, and documents connect — and set up rules that react automatically (a new file, an urgent email, a daily digest)." },
  { icon: "grid", title: "Model routing", desc: "Zenith auto-picks a model per message. Settings → Model routing shows which of your installed models actually fit your GPU comfortably." },
  { icon: "at-sign", title: "Email", desc: "Connect your own IMAP/SMTP account in Settings → Email for local summarize and draft-reply." },
  { icon: "sun", title: "8 themes", desc: "Settings → Appearance — full re-skins, not just light/dark, plus optional ambient backgrounds." },
  { icon: "share", title: "Multi-device sync", desc: "Settings → Sync — pair a second device with a one-time code, then export/import encrypted snapshots." },
];

/** Shown once on first launch (tracked via localStorage). Not a guided
 * click-through tour — just a compact map of what exists, since there's
 * now enough surface area that discoverability is the real risk. */
export default function OnboardingTour({ onClose }) {
  // step 0: "who are you" profile pick, step 1: profile-tailored summary,
  // step 2: the original feature map. Skipping/dismissing at any step
  // still just calls onClose, unchanged from before.
  const [step, setStep] = useState(0);
  const [profile, setProfile] = useState(null);

  function pickProfile(p) {
    setProfile(p);
    try {
      localStorage.setItem("zenith-profile", p.id);
    } catch {
      // storage unavailable — picking a profile is still fine, just not remembered
    }
    setStep(1);
  }

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div
        className="calendar-modal"
        style={{ width: "min(620px, calc(100vw - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-tour-title"
      >
        <div className="calendar-header">
          <span id="onboarding-tour-title">Welcome to Zenith</span>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        {step === 0 && (
          <div style={{ padding: "var(--space-2) var(--space-4) var(--space-4)" }}>
            <p className="settings-section-desc" style={{ marginTop: 0 }}>
              Everything here runs on your own machine — no cloud, no accounts. What are you
              mainly here for? We'll point out the handful of features that matter for that.
            </p>
            <div style={{ display: "grid", gap: "var(--space-2)" }}>
              {PROFILES.map((p) => (
                <button
                  key={p.id}
                  className="settings-btn-secondary"
                  style={{ textAlign: "left" }}
                  onClick={() => pickProfile(p)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <button
              className="settings-btn-secondary"
              style={{ marginTop: "var(--space-4)" }}
              onClick={() => setStep(2)}
            >
              Skip — just show me everything
            </button>
          </div>
        )}
        {step === 1 && profile && (
          <div style={{ padding: "var(--space-2) var(--space-4) var(--space-4)" }}>
            <p className="settings-section-desc" style={{ marginTop: 0 }}>
              Since you picked <strong>{profile.label}</strong>, here's what to try first:
            </p>
            <ul style={{ margin: 0, paddingLeft: "1.2rem", display: "grid", gap: "8px" }}>
              {profile.picks.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
            <button className="settings-btn-primary" style={{ marginTop: "var(--space-4)" }} onClick={() => setStep(2)}>
              Continue
            </button>
          </div>
        )}
        {step === 2 && (
          <div style={{ padding: "var(--space-2) var(--space-4) var(--space-4)" }}>
            <p className="settings-section-desc" style={{ marginTop: 0 }}>
              A few more things worth knowing exist:
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "var(--space-3)" }}>
              {HIGHLIGHTS.map((h) => (
                <div key={h.title} className="hw-summary" style={{ flexDirection: "column", alignItems: "flex-start", gap: "4px" }}>
                  <span style={{ display: "flex", alignItems: "center", gap: "6px", fontWeight: 600, color: "var(--text-primary)" }}>
                    <Icon name={h.icon} size={14} /> {h.title}
                  </span>
                  <span>{h.desc}</span>
                </div>
              ))}
            </div>
            <button className="settings-btn-primary" style={{ marginTop: "var(--space-4)" }} onClick={onClose}>
              Got it
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
