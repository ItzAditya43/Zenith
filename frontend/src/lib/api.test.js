import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// api.js resolves its BASE url once, at module-evaluation time, from
// import.meta.env.VITE_API_BASE / window.location. To exercise every branch
// of that logic we have to control those globals *before* importing the
// module, then re-import fresh (vi.resetModules) for each scenario.

function stubWindowLocation(protocol, hostname) {
  // The repo's own .env sets VITE_API_BASE=http://localhost:8420 for local
  // dev, which would otherwise always win over window-derived resolution
  // (see resolveBase()'s priority order). Force it empty here so tests can
  // exercise the window.location-derivation branch specifically; tests that
  // want the explicit-override behavior stub VITE_API_BASE themselves.
  vi.stubEnv("VITE_API_BASE", "");
  vi.stubGlobal("window", {
    location: { protocol, hostname, origin: `${protocol}//${hostname}`, pathname: "/index.html" },
  });
}

async function freshApi() {
  vi.resetModules();
  const mod = await import("./api.js");
  return mod.api;
}

beforeEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("resolveBase() / api.base", () => {
  it("uses an explicit VITE_API_BASE override when set, ignoring window.location", async () => {
    stubWindowLocation("http:", "some-other-host");
    vi.stubEnv("VITE_API_BASE", "https://explicit.example.com");
    const api = await freshApi();
    expect(api.base).toBe("https://explicit.example.com");
  });

  it("derives the base from window.location.hostname (LAN access)", async () => {
    stubWindowLocation("http:", "192.168.1.5");
    const api = await freshApi();
    expect(api.base).toBe("http://192.168.1.5:8420");
  });

  it("derives the base from a Tailscale-style hostname, preserving https", async () => {
    stubWindowLocation("https:", "my-laptop.tailnet-1234.ts.net");
    const api = await freshApi();
    expect(api.base).toBe("https://my-laptop.tailnet-1234.ts.net:8420");
  });

  it("uses window.location.hostname even when it is literally 'localhost'", async () => {
    stubWindowLocation("http:", "localhost");
    const api = await freshApi();
    expect(api.base).toBe("http://localhost:8420");
  });

  it("falls back to http://localhost:8420 when window is unavailable", async () => {
    vi.stubEnv("VITE_API_BASE", "");
    vi.stubGlobal("window", undefined);
    const api = await freshApi();
    expect(api.base).toBe("http://localhost:8420");
  });
});

describe("pure URL-builder helpers", () => {
  it("exportUrl builds a format-specific export URL", async () => {
    stubWindowLocation("http:", "localhost");
    const api = await freshApi();
    expect(api.exportUrl("json")).toBe("http://localhost:8420/api/export/json");
    expect(api.exportUrl("md")).toBe("http://localhost:8420/api/export/md");
  });

  it("conversationPdfUrl builds a per-conversation pdf export URL", async () => {
    stubWindowLocation("http:", "localhost");
    const api = await freshApi();
    expect(api.conversationPdfUrl("conv-42")).toBe(
      "http://localhost:8420/api/export/conv-42/pdf"
    );
  });

  it("attachmentDownloadUrl builds a per-attachment download URL", async () => {
    stubWindowLocation("http:", "localhost");
    const api = await freshApi();
    expect(api.attachmentDownloadUrl("att-1")).toBe(
      "http://localhost:8420/api/attachments/att-1/download"
    );
  });

  it("speakUrl points at the voice/speak endpoint", async () => {
    stubWindowLocation("http:", "localhost");
    const api = await freshApi();
    expect(api.speakUrl()).toBe("http://localhost:8420/api/voice/speak");
  });

  it("shareUrl builds a hash-route share link from window.location", async () => {
    vi.stubGlobal("window", {
      location: {
        protocol: "http:",
        hostname: "localhost",
        origin: "http://localhost:5173",
        pathname: "/app/",
      },
    });
    const api = await freshApi();
    expect(api.shareUrl("tok-123")).toBe("http://localhost:5173/app/#/share/tok-123");
  });
});

describe("unlockHeaders (via request())", () => {
  it("does not attach an unlock header when sessionStorage has no token", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => null) });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    vi.stubGlobal("fetch", fetchMock);

    const api = await freshApi();
    await api.listConversations();

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers).not.toHaveProperty("X-Zenith-Unlock");
  });

  it("attaches the X-Zenith-Unlock header when a token is present", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => "secret-token") });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    });
    vi.stubGlobal("fetch", fetchMock);

    const api = await freshApi();
    await api.listConversations();

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers).toMatchObject({ "X-Zenith-Unlock": "secret-token" });
  });

  it("caller-supplied headers are preserved alongside the unlock header", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => "secret-token") });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    });
    vi.stubGlobal("fetch", fetchMock);

    const api = await freshApi();
    await api.createConversation("Hello");

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers).toMatchObject({
      "X-Zenith-Unlock": "secret-token",
      "Content-Type": "application/json",
    });
  });
});

describe("request() error mapping", () => {
  it("throws an Error using the JSON body's `detail` field on a non-2xx response", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        statusText: "Bad Request",
        json: async () => ({ detail: "Conversation not found" }),
      })
    );

    const api = await freshApi();
    await expect(api.deleteConversation("missing")).rejects.toThrow("Conversation not found");
  });

  it("falls back to statusText when the error body isn't JSON", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        statusText: "Internal Server Error",
        json: async () => {
          throw new SyntaxError("Unexpected token < in JSON");
        },
      })
    );

    const api = await freshApi();
    await expect(api.deleteConversation("x")).rejects.toThrow("Internal Server Error");
  });

  it("falls back to statusText when the JSON body has no `detail` field", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        statusText: "Forbidden",
        json: async () => ({ message: "no detail key here" }),
      })
    );

    const api = await freshApi();
    await expect(api.deleteConversation("x")).rejects.toThrow("Forbidden");
  });

  it("resolves normally and parses JSON when the response is ok", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [{ id: "1", title: "Hi" }],
      })
    );

    const api = await freshApi();
    await expect(api.listConversations()).resolves.toEqual([{ id: "1", title: "Hi" }]);
  });
});

describe("api.health() (bypasses the generic request() error path)", () => {
  it("returns the parsed body on a 200 response", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok" }),
      })
    );

    const api = await freshApi();
    await expect(api.health()).resolves.toEqual({ status: "ok" });
  });

  it("returns body.detail (not a throw) on a 503 with a detail payload", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        statusText: "Service Unavailable",
        json: async () => ({ detail: { status: "down", components: {} } }),
      })
    );

    const api = await freshApi();
    await expect(api.health()).resolves.toEqual({ status: "down", components: {} });
  });

  it("throws using statusText when a failed response has no usable body", async () => {
    stubWindowLocation("http:", "localhost");
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        statusText: "Service Unavailable",
        json: async () => {
          throw new SyntaxError("not json");
        },
      })
    );

    const api = await freshApi();
    await expect(api.health()).rejects.toThrow("Service Unavailable");
  });
});

// consumeSSEBody / streamSSE's chunk-parsing loop is intentionally left
// untested here: it's an inner, non-exported function tightly coupled to a
// real ReadableStream reader (`res.body.getReader()`), and faking that
// faithfully (partial chunk boundaries across `reader.read()` calls, the
// `\n\n` frame-splitting, backpressure) would mean re-implementing enough of
// the Streams API that the test would mostly be validating the mock, not
// api.js. That needs an actual backend (or a fuller integration harness)
// and is out of scope for this pure-logic unit-test pass.
