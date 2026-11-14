/**
 * In-app replacements for window.confirm / window.prompt, rendered by
 * <DialogHost /> (mounted once in App). The browser's own dialogs are drawn
 * by the OS (GTK on Linux, inside the desktop app) and ignore Zenith's
 * theme. These return promises so call sites stay short:
 *
 *   if (!(await confirmDialog({ title: "Delete chat?", danger: true }))) return;
 *   const name = await promptDialog({ title: "Project name" });
 */

let items = [];
const listeners = new Set();

function emit() {
  for (const l of listeners) l();
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function snapshot() {
  return items;
}

export function settle(item, result) {
  items = items.filter((x) => x !== item);
  emit();
  item.resolve(result);
}

function open(spec) {
  return new Promise((resolve) => {
    items = [...items, { ...spec, resolve }];
    emit();
  });
}

export function confirmDialog({ title, message = "", confirmLabel = "OK", cancelLabel = "Cancel", danger = false } = {}) {
  return open({ kind: "confirm", title, message, confirmLabel, cancelLabel, danger });
}

export function promptDialog({
  title, message = "", defaultValue = "", placeholder = "", confirmLabel = "OK", cancelLabel = "Cancel",
  multiline = false, allowEmpty = false,
} = {}) {
  return open({ kind: "prompt", title, message, defaultValue, placeholder, confirmLabel, cancelLabel, multiline, allowEmpty });
}
