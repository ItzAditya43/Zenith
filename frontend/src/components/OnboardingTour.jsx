import Icon from "./Icon.jsx";

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
        <div style={{ padding: "var(--space-2) var(--space-4) var(--space-4)" }}>
          <p className="settings-section-desc" style={{ marginTop: 0 }}>
            Everything here runs on your own machine — no cloud, no accounts. A few things worth
            knowing exist:
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
      </div>
    </div>
  );
}
