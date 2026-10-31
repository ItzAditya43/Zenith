// UI audit screenshots: `AUDIT=1 npx playwright test e2e/audit.spec.ts`
import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8421";
const OUT = "audit-shots";
test.skip(!process.env.AUDIT, "set AUDIT=1");

async function prep(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("zenith-onboarded", "1");
    sessionStorage.setItem("zenith-booted", "1");
  });
  await page.request.patch(`${API}/api/config`, { data: { agent_enabled: true, agent_mode: "manual" } });
  await page.goto("/");
  if ((page.viewportSize()?.width ?? 1440) < 720) {
    await page.locator("header.chat-header .mobile-menu-btn").click();
    await page.screenshot({ path: `${OUT}/mobile-00-sidebar.png` });
  }
  await page.locator(".new-chat-btn").click();
}

async function chat(page: Page) {
  await page.locator("textarea").first().fill("Give me a weekly review template [demo]");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Clear the decks")).toBeVisible();
}

for (const [label, size] of [["desktop", { width: 1440, height: 900 }], ["mobile", { width: 390, height: 844 }]] as const) {
  test(`audit ${label}`, async ({ page }) => {
    await page.setViewportSize(size);
    await prep(page);
    await page.screenshot({ path: `${OUT}/${label}-01-empty.png` });
    await chat(page);
    await page.screenshot({ path: `${OUT}/${label}-02-chat.png` });
    await page.locator("textarea").first().fill("/agent write a hello file");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator(".tool-call-pending")).toBeVisible();
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${OUT}/${label}-02b-agent.png` });
    await page.keyboard.press("y");
    await expect(page.getByText("Wrote e2e.txt")).toBeVisible();
    await page.screenshot({ path: `${OUT}/${label}-02c-agent-done.png` });
    // Model picker with a long, mixed local/cloud list (matches a real
    // Ollama Cloud-enabled install) — exercises search, grouping, and the
    // bounded-height scroll instead of growing past the window. Mocked
    // then reloaded so the app's mount-time model fetch picks it up.
    await page.route("**/api/models", (route) =>
      route.fulfill({
        json: [
          "llama3.2:3b", "qwen2.5-coder:7b", "qwen2.5vl:3b", "qwen3.5:2b", "qwen3.5:4b",
          "qwen3.5:latest", "qwen2.5-coder:3b", "llava:7b", "llama3:latest",
          "devstral-2:123b-cloud", "deepseek-v4-flash:cloud", "deepseek-v4-pro:cloud",
          "glm-5.1:cloud", "minimax-m3:cloud", "nemotron-3-ultra:cloud",
        ].map((name) => ({ name, roles: [], cloud: name.includes("cloud") })),
      })
    );
    await page.reload();
    if ((page.viewportSize()?.width ?? 1440) < 720) {
      await page.locator("header.chat-header .mobile-menu-btn").click();
    }
    await page.locator(".new-chat-btn").click();
    await page.locator('[aria-label="Auto (model routing)"], [title^="Model:"]').click();
    await expect(page.locator(".model-override-menu")).toBeVisible();
    await page.screenshot({ path: `${OUT}/${label}-02d-model-picker.png` });
    await page.getByPlaceholder("Search models…").fill("cloud");
    await page.screenshot({ path: `${OUT}/${label}-02e-model-picker-search.png` });
    await page.keyboard.press("Escape");

    await page.getByRole("button", { name: "More panels" }).click();
    await expect(page.locator(".header-more-panel")).toBeVisible();
    await page.screenshot({ path: `${OUT}/${label}-02f-header-more.png` });
    await page.keyboard.press("Escape");

    await page.keyboard.press("Control+k");
    await page.screenshot({ path: `${OUT}/${label}-03-palette.png` });
    await page.keyboard.press("Escape");
    await page.keyboard.press("Control+k");
    await page.getByLabel("Search commands").fill("Settings — Appearance");
    await page.keyboard.press("Enter");
    const nav = page.getByRole("navigation", { name: "Settings sections" });
    await expect(nav).toBeVisible();
    await page.screenshot({ path: `${OUT}/${label}-04-settings.png` });
    await nav.getByRole("button", { name: "Model routing" }).click();
    await page.screenshot({ path: `${OUT}/${label}-05-routing.png` });
  });
}
