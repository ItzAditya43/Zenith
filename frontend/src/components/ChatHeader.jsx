import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";
import StatusRail from "./StatusRail.jsx";
import { api } from "../lib/api";

/** The chat header toolbar, extracted from App.jsx. App owns all state; this is presentational. */
/** Secondary panels live behind one labelled "More" menu instead of a row of
 * fourteen unlabeled icons (which also overflowed the header on phones). */
function HeaderMoreGroup({ label, children }) {
  return (
    <div className="header-more-group" role="presentation">
      <p className="header-more-group-label">{label}</p>
      {children}
    </div>
  );
}

function HeaderMore({ children }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const away = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <div className="header-more" ref={ref}>
      <button
        className={`icon-btn ${open ? "is-active" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="More panels"
        title="More panels"
      >
        <Icon name="grid" size={16} />
      </button>
      {open && (
        <div className="header-more-panel" role="menu" onClick={() => setOpen(false)}>
          {children}
        </div>
      )}
    </div>
  );
}

export default function ChatHeader({
  activeId,
  messages,
  setSidebarCollapsed,
  genStats,
  voiceReplyEnabled,
  setVoiceReplyEnabled,
  continuousVoice,
  setContinuousVoice,
  focusMode,
  setFocusMode,
  agentAvailable,
  personas,
  branches,
  branchTreeOpen,
  setBranchTreeOpen,
  calendarOpen,
  setCalendarOpen,
  notesOpen,
  setNotesOpen,
  todosOpen,
  setTodosOpen,
  researchOpen,
  setResearchOpen,
  codeEditorOpen,
  setCodeEditorOpen,
  snippetsOpen,
  setSnippetsOpen,
  graphOpen,
  setGraphOpen,
  digestOpen,
  setDigestOpen,
  setQuickActions,
  usageOpen,
  setUsageOpen,
  healthOpen,
  setHealthOpen,
  ragSourcesOpen,
  setRagSourcesOpen,
  backupOpen,
  setBackupOpen,
  settingsHistoryOpen,
  setSettingsHistoryOpen,
  batchJobOpen,
  setBatchJobOpen,
  groupPersonaIds,
  setGroupPickerOpen,
  handlePersonaChange,
  handleSetWorkdir,
  handleExtractProject,
  handleShare,
  activeConversation,
  openSettingsAt,
}) {
  return (
    <header className="chat-header">
      <button
        className="mobile-menu-btn"
        onClick={() => setSidebarCollapsed((v) => !v)}
        title="Toggle sidebar"
        aria-label="Toggle sidebar"
      >
        <Icon name="menu" size={18} />
      </button>
      <h1>{activeConversation?.title || "Zenith"}</h1>
      <StatusRail genStats={genStats} />
      <div className="header-actions">
        <HeaderMore>
          <HeaderMoreGroup label="Workspace">
            {Object.values(branches).some((s) => s.length > 1) && (
              <button
                className={`icon-btn branch-tree-toggle ${branchTreeOpen ? "is-active" : ""}`}
                onClick={() => setBranchTreeOpen((v) => !v)}
                title="Branch tree — see and switch between alternate versions"
                aria-label="Branch tree"
              >
                <Icon name="layers" size={16} />
                <span className="header-more-label">Branch tree</span>
              </button>
            )}
            {!focusMode && (
              <button
                className={`icon-btn ${calendarOpen ? "is-active" : ""}`}
                onClick={() => setCalendarOpen((v) => !v)}
                title="Calendar"
                aria-label="Calendar"
              >
                <Icon name="clock" size={16} />
                <span className="header-more-label">Calendar</span>
              </button>
            )}
            {!focusMode && (
              <button
                className={`icon-btn ${notesOpen ? "is-active" : ""}`}
                onClick={() => setNotesOpen((v) => !v)}
                title="Notes"
                aria-label="Notes"
              >
                <Icon name="pencil" size={16} />
                <span className="header-more-label">Notes</span>
              </button>
            )}
            {!focusMode && (
              <button
                className={`icon-btn ${todosOpen ? "is-active" : ""}`}
                onClick={() => setTodosOpen((v) => !v)}
                title="To-do"
                aria-label="To-do"
              >
                <Icon name="check" size={16} />
                <span className="header-more-label">To-do</span>
              </button>
            )}
          </HeaderMoreGroup>
          {!focusMode && (
            <HeaderMoreGroup label="Reports &amp; knowledge">
              <button
                className={`icon-btn ${researchOpen ? "is-active" : ""}`}
                onClick={() => setResearchOpen((v) => !v)}
                title="Research reports"
                aria-label="Research reports"
              >
                <Icon name="flask" size={16} />
                <span className="header-more-label">Research reports</span>
              </button>
              <button
                className={`icon-btn ${snippetsOpen ? "is-active" : ""}`}
                onClick={() => {
                  setSnippetsOpen((v) => !v);
                  api.listQuickActions().then(setQuickActions).catch(() => {});
                }}
                title="Prompt snippets"
                aria-label="Prompt snippets"
              >
                <Icon name="copy" size={16} />
                <span className="header-more-label">Prompt snippets</span>
              </button>
              <button
                className={`icon-btn ${graphOpen ? "is-active" : ""}`}
                onClick={() => setGraphOpen((v) => !v)}
                title="Knowledge graph — how conversations, memories, and documents connect"
                aria-label="Knowledge graph"
              >
                <Icon name="share" size={16} />
                <span className="header-more-label">Knowledge graph</span>
              </button>
              <button
                className={`icon-btn ${digestOpen ? "is-active" : ""}`}
                onClick={() => setDigestOpen((v) => !v)}
                title="Daily digest"
                aria-label="Daily digest"
              >
                <Icon name="sun" size={16} />
                <span className="header-more-label">Daily digest</span>
              </button>
              <button
                className={`icon-btn ${ragSourcesOpen ? "is-active" : ""}`}
                onClick={() => setRagSourcesOpen((v) => !v)}
                title="RAG sources — what's indexed for retrieval"
                aria-label="RAG sources"
              >
                <Icon name="layers" size={16} />
                <span className="header-more-label">RAG sources</span>
              </button>
            </HeaderMoreGroup>
          )}
          {!focusMode && (
            <HeaderMoreGroup label="System">
              <button
                className={`icon-btn ${usageOpen ? "is-active" : ""}`}
                onClick={() => setUsageOpen((v) => !v)}
                title="Usage & diagnostics"
                aria-label="Usage"
              >
                <Icon name="bar-chart" size={16} />
                <span className="header-more-label">Usage</span>
              </button>
              <button
                className={`icon-btn ${healthOpen ? "is-active" : ""}`}
                onClick={() => setHealthOpen((v) => !v)}
                title="System health"
                aria-label="System health"
              >
                <Icon name="target" size={16} />
                <span className="header-more-label">System health</span>
              </button>
              <button
                className={`icon-btn ${settingsHistoryOpen ? "is-active" : ""}`}
                onClick={() => setSettingsHistoryOpen((v) => !v)}
                title="Settings history — see and revert changes"
                aria-label="Settings history"
              >
                <Icon name="rotate-ccw" size={16} />
                <span className="header-more-label">Settings history</span>
              </button>
              <button
                className={`icon-btn ${batchJobOpen ? "is-active" : ""}`}
                onClick={() => setBatchJobOpen((v) => !v)}
                title="Batch job — run a prompt against every file in a folder"
                aria-label="Batch job"
              >
                <Icon name="hourglass" size={16} />
                <span className="header-more-label">Batch job</span>
              </button>
              <button
                className={`icon-btn ${backupOpen ? "is-active" : ""}`}
                onClick={() => setBackupOpen((v) => !v)}
                title="Backup & restore"
                aria-label="Backup"
              >
                <Icon name="folder-open" size={16} />
                <span className="header-more-label">Backup</span>
              </button>
            </HeaderMoreGroup>
          )}
        </HeaderMore>
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
        {!focusMode && activeConversation?.workdir && (
          <button
            className={`icon-btn ${codeEditorOpen ? "is-active" : ""}`}
            onClick={() => setCodeEditorOpen((v) => !v)}
            title={`Open code editor for ${activeConversation.workdir}`}
          >
            <Icon name="terminal" size={16} />
          </button>
        )}
        {!focusMode && activeId && (
          <button
            className={`icon-btn ${activeConversation?.share_token ? "is-active" : ""}`}
            onClick={handleShare}
            title={activeConversation?.share_token ? "Revoke share link" : "Create a read-only share link"}
          >
            <Icon name="share" size={16} />
          </button>
        )}
        {!focusMode && activeId && (
          <button
            className="icon-btn"
            onClick={handleExtractProject}
            title="Extract this conversation's code blocks into real files and open the code editor"
          >
            <Icon name="download" size={16} />
          </button>
        )}
        {!focusMode && activeId && messages.length > 0 && (
          <a
            className="icon-btn"
            href={api.conversationPdfUrl(activeId)}
            download
            title="Download this conversation as a PDF"
            aria-label="Download this conversation as a PDF"
          >
            <Icon name="file-text" size={16} />
          </a>
        )}
        {!focusMode && personas.length > 0 && groupPersonaIds.length < 2 && (
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
        {!focusMode && personas.length >= 2 && (
          <button
            className={`icon-btn ${groupPersonaIds.length >= 2 ? "is-active" : ""}`}
            onClick={() => setGroupPickerOpen((v) => !v)}
            title={groupPersonaIds.length >= 2 ? `Group chat: ${groupPersonaIds.length} personas` : "Set up a group chat"}
          >
            <Icon name="users" size={16} />
            {groupPersonaIds.length >= 2 && <span style={{ marginLeft: 4, fontSize: "0.75em" }}>{groupPersonaIds.length}</span>}
          </button>
        )}
        <div className="header-tool-group">
          {!focusMode && (
            <button
              className="icon-btn"
              onClick={() => openSettingsAt("appearance")}
              title="Change theme"
            >
              <Icon name="sun" size={16} />
            </button>
          )}
          {!focusMode && (
            <button
              className={`icon-btn ${voiceReplyEnabled ? "is-active" : ""}`}
              onClick={() => setVoiceReplyEnabled((v) => !v)}
              title={voiceReplyEnabled ? "Spoken replies on" : "Spoken replies off"}
            >
              <Icon name={voiceReplyEnabled ? "volume-2" : "volume-x"} size={16} />
            </button>
          )}
          {!focusMode && (
            <button
              className={`icon-btn ${continuousVoice ? "is-active" : ""}`}
              onClick={() => {
                const next = !continuousVoice;
                setContinuousVoice(next);
                if (next) setVoiceReplyEnabled(true); // the loop needs spoken replies to keep going
              }}
              title={continuousVoice ? "Hands-free voice mode on" : "Hands-free conversation: speak, hear the reply, mic reopens automatically"}
            >
              <Icon name="headphones" size={16} />
            </button>
          )}
          <button
            className={`icon-btn ${focusMode ? "is-active" : ""}`}
            onClick={() => setFocusMode((v) => !v)}
            title={focusMode ? "Exit focus mode (⌘. or Esc)" : "Focus mode — hide sidebar and chrome (⌘.)"}
          >
            <Icon name="target" size={16} />
          </button>
        </div>
      </div>
    </header>
  );
}
