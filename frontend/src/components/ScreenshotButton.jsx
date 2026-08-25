import { useState } from "react";
import Icon from "./Icon.jsx";

// True only inside the Tauri desktop shell — never in the Docker/browser
// deployment, where there's no native screenshot capability at all. Standard
// Tauri v2 detection: the injected `window.__TAURI__` global only exists
// inside a Tauri webview.
function isDesktopApp() {
  return typeof window !== "undefined" && typeof window.__TAURI__ !== "undefined";
}

// User-initiated, read-only screenshot capture for attaching a screenshot to
// the composer. Renders nothing outside the desktop app (see isDesktopApp
// above) so it doesn't show up broken in the web/Docker deployment, which
// has no way to capture the screen.
//
// Props:
//   onCapture(dataUrl) — called with a "data:image/png;base64,..." string
//     once the screenshot is captured. What happens with it (attach to the
//     composer, preview it, etc.) is left to the caller.
export default function ScreenshotButton({ onCapture }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!isDesktopApp()) return null;

  const handleClick = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const dataUrl = await invoke("capture_screenshot");
      if (typeof onCapture === "function") {
        onCapture(dataUrl);
      }
    } catch (err) {
      setError(typeof err === "string" ? err : err?.message || "Screenshot capture failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      className="composer-icon-btn"
      onClick={handleClick}
      disabled={busy}
      title={error || "Attach a screenshot"}
      aria-label={error || "Attach a screenshot"}
      aria-busy={busy}
    >
      <Icon name={busy ? "hourglass" : "image"} size={17} />
    </button>
  );
}
