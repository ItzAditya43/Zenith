// Tiny app-wide events for opening panels from anywhere (a chip in a
// message, a Settings button, the command palette) without threading
// callbacks through every component in between.
export const openMemoryBrowser = (focusId = null) =>
  window.dispatchEvent(new CustomEvent("zenith:open-memory", { detail: { focusId } }));
