// Tiny app-wide events for opening panels from anywhere (a chip in a
// message, a Settings button, the command palette) without threading
// callbacks through every component in between.
export const openMemoryBrowser = (focusId = null) =>
  window.dispatchEvent(new CustomEvent("zenith:open-memory", { detail: { focusId } }));
export const openTasks = (focusId = null) =>
  window.dispatchEvent(new CustomEvent("zenith:open-tasks", { detail: { focusId } }));
export const openRunReview = (runId) =>
  window.dispatchEvent(new CustomEvent("zenith:open-run-review", { detail: { runId } }));
export const openChatManager = (show = "active") =>
  window.dispatchEvent(new CustomEvent("zenith:open-chats", { detail: { show } }));
export const openModelCompare = () => window.dispatchEvent(new CustomEvent("zenith:open-compare"));
export const openNotifications = () => window.dispatchEvent(new CustomEvent("zenith:open-notifications"));
export const openCleanup = () => window.dispatchEvent(new CustomEvent("zenith:open-cleanup"));
export const openInWorkspace = (path, line = null) =>
  window.dispatchEvent(new CustomEvent("zenith:open-in-workspace", { detail: { path, line } }));
export const openMail = () => window.dispatchEvent(new CustomEvent("zenith:open-mail"));
export const openConversation = (id) => window.dispatchEvent(new CustomEvent("zenith:open-conversation", { detail: { id } }));
