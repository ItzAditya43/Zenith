// Helper to invoke the native OS directory picker dialog when running inside
// the Tauri desktop app, with safe fallbacks.

export function isDesktopApp(): boolean {
  return (
    typeof window !== "undefined" &&
    ("__TAURI__" in window ||
      "__TAURI_INTERNALS__" in window ||
      window.location?.protocol === "tauri:" ||
      window.location?.hostname === "tauri.localhost")
  );
}

export interface PickDirectoryOptions {
  defaultPath?: string;
  title?: string;
}

/**
 * Opens the native OS directory picker dialog (GTK on Linux, Finder on macOS,
 * Explorer on Windows) via Tauri's dialog plugin. Returns the chosen path string,
 * or null if the user cancelled or if native dialogs are unavailable.
 */
export async function pickNativeDirectory(
  options: PickDirectoryOptions = {}
): Promise<string | null> {
  if (!isDesktopApp()) return null;

  const { defaultPath, title = "Select Working Directory" } = options;

  try {
    // 1. If injected on window.__TAURI__.dialog
    const winTauri = (window as unknown as { __TAURI__?: { dialog?: { open: (opts: unknown) => Promise<unknown> } } }).__TAURI__;
    if (typeof winTauri?.dialog?.open === "function") {
      const res = await winTauri.dialog.open({
        directory: true,
        multiple: false,
        defaultPath: defaultPath || undefined,
        title,
      });
      if (res && typeof res === "string") return res;
      if (Array.isArray(res) && res.length > 0) return String(res[0]);
      return null;
    }

    // 2. Invoke through @tauri-apps/api/core
    const { invoke } = await import("@tauri-apps/api/core");
    const res = await invoke<string | string[] | null>("plugin:dialog|open", {
      options: {
        directory: true,
        multiple: false,
        defaultPath: defaultPath || undefined,
        title,
      },
    });

    if (res && typeof res === "string") return res;
    if (Array.isArray(res) && res.length > 0) return String(res[0]);
    return null;
  } catch (err) {
    console.warn("Native directory picker invocation failed:", err);
    return null;
  }
}

