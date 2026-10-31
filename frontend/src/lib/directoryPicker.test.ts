import { describe, it, expect, vi, beforeEach } from "vitest";
import { isDesktopApp, pickNativeDirectory } from "./directoryPicker";

describe("directoryPicker", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe("isDesktopApp", () => {
    it("returns false in standard browser environment", () => {
      vi.stubGlobal("window", {
        location: { protocol: "http:", hostname: "localhost" },
      });
      expect(isDesktopApp()).toBe(false);
    });

    it("returns true when __TAURI__ global exists", () => {
      vi.stubGlobal("window", {
        __TAURI__: {},
        location: { protocol: "http:", hostname: "localhost" },
      });
      expect(isDesktopApp()).toBe(true);
    });

    it("returns true when __TAURI_INTERNALS__ exists", () => {
      vi.stubGlobal("window", {
        __TAURI_INTERNALS__: {},
        location: { protocol: "http:", hostname: "localhost" },
      });
      expect(isDesktopApp()).toBe(true);
    });

    it("returns true for tauri: protocol", () => {
      vi.stubGlobal("window", {
        location: { protocol: "tauri:", hostname: "localhost" },
      });
      expect(isDesktopApp()).toBe(true);
    });

    it("returns true for tauri.localhost hostname", () => {
      vi.stubGlobal("window", {
        location: { protocol: "http:", hostname: "tauri.localhost" },
      });
      expect(isDesktopApp()).toBe(true);
    });
  });

  describe("pickNativeDirectory", () => {
    it("returns null when not in desktop app", async () => {
      vi.stubGlobal("window", {
        location: { protocol: "http:", hostname: "localhost" },
      });
      const res = await pickNativeDirectory();
      expect(res).toBeNull();
    });

    it("invokes window.__TAURI__.dialog.open when present", async () => {
      const mockOpen = vi.fn().mockResolvedValue("/home/user/project");
      vi.stubGlobal("window", {
        __TAURI__: {
          dialog: { open: mockOpen },
        },
        location: { protocol: "tauri:", hostname: "localhost" },
      });

      const res = await pickNativeDirectory({ defaultPath: "/home/user" });
      expect(res).toBe("/home/user/project");
      expect(mockOpen).toHaveBeenCalledWith(
        expect.objectContaining({
          directory: true,
          multiple: false,
          defaultPath: "/home/user",
        })
      );
    });

    it("handles cancel from dialog", async () => {
      const mockOpen = vi.fn().mockResolvedValue(null);
      vi.stubGlobal("window", {
        __TAURI__: {
          dialog: { open: mockOpen },
        },
        location: { protocol: "tauri:", hostname: "localhost" },
      });

      const res = await pickNativeDirectory();
      expect(res).toBeNull();
    });
  });
});

