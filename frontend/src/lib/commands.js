/** Builds the command-palette entries. Pure: everything comes in through `ctx`
 * (App passes its state, setters and a ref to the latest handlers). */
export function buildCommands({
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
}) {
  const list = [];
  list.push({
    id: "new-chat", group: "Actions", icon: "plus", label: "New chat",
    action: handleCreate,
  });
  list.push({
    id: "open-appearance", group: "Actions", icon: "sun",
    label: "Change theme",
    action: () => openSettingsAt("appearance"),
  });
  list.push({
    id: "whats-new", group: "Actions", icon: "bolt",
    label: "What's new",
    action: () => setWhatsNewOpen(true),
  });
  list.push({
    id: "replay-onboarding", group: "Actions", icon: "book-open",
    label: "Replay welcome tour",
    action: () => setOnboardingOpen(true),
  });
  list.push({
    id: "keyboard-shortcuts", group: "Actions", icon: "command",
    label: "Keyboard shortcuts",
    hint: "?",
    action: () => setShortcutsOpen(true),
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
    id: "open-traces", group: "Actions", icon: "layers",
    label: "Show turn traces (routing, context, tool calls, timing)",
    action: () => setTracesOpen(true),
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
      action: () => paletteHandlers.current.handleSetWorkdir(),
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
      action: () => paletteHandlers.current.handlePersonaChange(p.id),
    });
  }
  if (activeConversation?.persona_id) {
    list.push({
      id: "persona-none", group: "Personas", icon: "x", label: "Remove persona from this conversation",
      action: () => paletteHandlers.current.handlePersonaChange(null),
    });
  }
  for (const c of conversations) {
    list.push({
      id: `conv-${c.id}`, group: "Conversations", icon: "message-circle", label: c.title,
      action: () => selectConversation(c.id),
    });
  }
  for (const a of quickActions) {
    list.push({
      id: `quick-action-${a.id}`, group: "Quick actions", icon: a.auto_send ? "bolt" : "copy",
      label: a.name,
      action: () => {
        if (a.auto_send) {
          paletteHandlers.current.handleSend(a.prompt_template, []);
        } else {
          setSeedText({ text: a.prompt_template, nonce: Date.now() });
        }
      },
    });
  }
  return list;
}
