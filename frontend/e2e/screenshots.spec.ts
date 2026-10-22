// Regenerates the README screenshots (agent approval + settings; chat shots
// would show the fake model's canned replies): `npm run screenshots`.
// Skipped in the normal e2e run (needs SCREENSHOTS=1).
import { expect, test } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const API = "http://127.0.0.1:8421";
const OUT = "../docs/assets";

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to regenerate docs images");
test.use({ viewport: { width: 1440, height: 900 }, colorScheme: "dark" });

test("readme screenshots", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("zenith-onboarded", "1"));
  await page.request.patch(`${API}/api/config`, { data: { agent_enabled: true, agent_mode: "manual", memory_enabled: false } });
  await page.goto("/");

  const box = page.locator("textarea").first();
  await page.locator(".new-chat-btn").click();
  const convs = await (await page.request.get(`${API}/api/conversations`)).json();
  const convId = (convs[0] ?? convs.conversations?.[0]).id;
  await page.request.patch(`${API}/api/conversations/${convId}/workdir`, { data: { workdir: mkdtempSync(join(tmpdir(), "zenith-shot-agent-")) } });
  await page.locator(".mode-picker-btn").click();
  await page.getByRole("option", { name: /Agent/ }).click();
  await box.fill("Create a short e2e.txt file for me");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("button", { name: /^Approve$/ })).toBeVisible();
  await page.screenshot({ path: `${OUT}/screenshot-agent-approval.png` });

  await page.getByRole("button", { name: "Settings" }).first().click();
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("button", { name: "Agent tools" }).click();
  await page.screenshot({ path: `${OUT}/screenshot-settings.png` });
});
