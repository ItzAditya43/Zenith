import { useEffect } from "react";

const ICON = { info: "ℹ", success: "✓", error: "⚠" };

export default function ToastStack({ toasts, onDismiss }) {
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  );
}

function Toast({ toast, onDismiss }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, toast.duration || 4000);
    return () => clearTimeout(timer);
  }, [toast, onDismiss]);

  return (
    <div className={`toast toast-${toast.type || "info"}`} onClick={onDismiss}>
      <span className="toast-icon" aria-hidden="true">
        {ICON[toast.type] || ICON.info}
      </span>
      <span className="toast-message">{toast.message}</span>
    </div>
  );
}
