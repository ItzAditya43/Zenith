import { defineConfig, devices } from "@playwright/test";

// End-to-end: the real React app + the real FastAPI backend, with Ollama
// replaced by e2e/fake_ollama.py so runs are deterministic and offline.
// Ports are offset from the defaults (8420/5173/11434) so the suite can run
// next to a normal Zenith install. E2E_PYTHON picks the interpreter that has
// backend/requirements.txt installed (defaults to `python3`).
const PY = process.env.E2E_PYTHON || "python3";
const BACKEND = "http://127.0.0.1:8421";
const FRONTEND = "http://127.0.0.1:5174";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false, // one backend + one SQLite file shared by all tests
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: FRONTEND,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        permissions: ["microphone"],
        launchOptions: { args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] },
      },
    },
  ],
  webServer: [
    {
      command: `${PY} e2e/fake_ollama.py 11555`,
      url: "http://127.0.0.1:11555/api/tags",
      reuseExistingServer: false,
    },
    {
      command: `sh -c 'rm -rf e2e/.data && cd ../backend && exec ${PY} -m uvicorn app.main:app --host 127.0.0.1 --port 8421'`,
      url: `${BACKEND}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        ZENITH_DATA_DIR: `${process.cwd()}/e2e/.data`,
        OLLAMA_HOST: "http://127.0.0.1:11555",
        CORS_ALLOW_ORIGINS: `${FRONTEND},http://localhost:5174`,
      },
    },
    {
      command: "npx vite --host 127.0.0.1 --port 5174 --strictPort",
      url: FRONTEND,
      reuseExistingServer: false,
      env: { VITE_API_BASE: BACKEND },
    },
  ],
});
