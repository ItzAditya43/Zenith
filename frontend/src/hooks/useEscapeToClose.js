import { useEffect } from "react";

/** Closes a modal/overlay on Escape — the keyboard-only equivalent of
 * clicking the backdrop, which several panels only supported by mouse. */
export function useEscapeToClose(onClose) {
  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);
}
