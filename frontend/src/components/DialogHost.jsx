import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { settle, snapshot, subscribe } from "../lib/dialogs.js";

/** Renders the dialogs opened with confirmDialog / promptDialog
 * (lib/dialogs.js). Mounted once in App. */
export default function DialogHost() {
  const items = useSyncExternalStore(subscribe, snapshot);
  const current = items[0] || null;
  const [value, setValue] = useState("");
  const inputRef = useRef(null);
  const confirmRef = useRef(null);
  const [shownFor, setShownFor] = useState(null);

  // Reset the text field when a new dialog comes up (render-time pattern).
  if (current !== shownFor) {
    setShownFor(current);
    if (current?.kind === "prompt") setValue(current.defaultValue || "");
  }

  useEffect(() => {
    if (!current) return;
    const t = setTimeout(() => {
      if (current.kind === "prompt") {
        inputRef.current?.focus();
        inputRef.current?.select?.();
      } else {
        confirmRef.current?.focus();
      }
    }, 20);
    return () => clearTimeout(t);
  }, [current]);

  if (!current) return null;

  const close = (result) => settle(current, result);
  const ok = () => close(current.kind === "prompt" ? value : true);
  const cancel = () => close(current.kind === "prompt" ? null : false);

  return (
    <div
      className="app-dialog-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) cancel();
      }}
    >
      <form
        className="app-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="app-dialog-title"
        aria-describedby={current.message ? "app-dialog-message" : undefined}
        onSubmit={(e) => {
          e.preventDefault();
          ok();
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            cancel();
          }
        }}
      >
        <h2 id="app-dialog-title" className="app-dialog-title">{current.title}</h2>
        {current.message && <p id="app-dialog-message" className="app-dialog-message">{current.message}</p>}
        {current.kind === "prompt" &&
          (current.multiline ? (
            <textarea
              ref={inputRef}
              className="settings-input app-dialog-input"
              rows={4}
              value={value}
              placeholder={current.placeholder}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  ok();
                }
              }}
            />
          ) : (
            <input
              ref={inputRef}
              className="settings-input app-dialog-input"
              value={value}
              placeholder={current.placeholder}
              onChange={(e) => setValue(e.target.value)}
            />
          ))}
        <div className="app-dialog-actions">
          <button type="button" className="app-dialog-btn" onClick={cancel}>{current.cancelLabel}</button>
          <button
            type="submit"
            ref={confirmRef}
            className={`app-dialog-btn ${current.danger ? "app-dialog-btn-danger" : "app-dialog-btn-primary"}`}
            disabled={current.kind === "prompt" && !current.allowEmpty && !value.trim()}
          >
            {current.confirmLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
