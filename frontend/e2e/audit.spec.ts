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
    await page.keyboard.press("Control+k");
    await page.screenshot({ path: `${OUT}/${label}-03-palette.png` });
    await page.keyboard.press("Escape");
    await page.keyboard.press("Control+k");
    await page.getByLabel("Search commands").fill("Settings — Appearance");
    await page.keyboard.press("Enter");
    await page.screenshot({ path: `${OUT}/${label}-04-settings.png` });
    const nav = page.getByRole("navigation", { name: "Settings sections" });
    await expect(nav).toBeVisible();
    await nav.getByRole("button", { name: "Model routing" }).click();
    await page.screenshot({ path: `${OUT}/${label}-05-routing.png` });
  });
}
