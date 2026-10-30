import { expect, test, type Page } from "@playwright/test";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const API = "http://127.0.0.1:8421";

async function patchConfig(page: Page, patch: Record<string, unknown>) {
  const res = await page.request.patch(`${API}/api/config`, { data: patch });
  expect(res.ok()).toBeTruthy();
}

test.beforeEach(async ({ page }) => {
  // Skip the first-run tour so it doesn't cover the composer.
  await page.addInitScript(() => {
    localStorage.setItem("zenith-onboarded", "1");
    sessionStorage.setItem("zenith-booted", "1");
  });
  await patchConfig(page, { agent_enabled: false, memory_enabled: false });
  await page.goto("/");
  await page.locator(".new-chat-btn").click();
});

async function send(page: Page, text: string) {
  const box = page.locator("textarea").first();
  await box.fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

test("sends a message and streams the reply", async ({ page }) => {
  await send(page, "Hello from the e2e suite");
  await expect(page.getByText("Echo: Hello from the e2e suite")).toBeVisible();
});

test("answers from an uploaded document via RAG", async ({ page }) => {
  const dir = mkdtempSync(join(tmpdir(), "zenith-e2e-"));
  const file = join(dir, "budget.txt");
  writeFileSync(file, "The Q3 marketing budget is 42 thousand euros.");
  await page.locator('input[type="file"]').first().setInputFiles(file);
  await expect(page.getByText("budget.txt").first()).toBeVisible();
  // Give background indexing a moment, then ask.
  await page.waitForTimeout(1000);
  await send(page, "What is the Q3 marketing budget?");
  await expect(page.getByText(/Echo: What is the Q3 marketing budget\?/)).toBeVisible();
  await expect(page.getByText(/docs: budget\.txt/)).toBeVisible();
});

test("agent mode pauses for approval and writes the file once approved", async ({ page }) => {
  const workdir = mkdtempSync(join(tmpdir(), "zenith-e2e-agent-"));
  await patchConfig(page, { agent_enabled: true, agent_mode: "manual", agent_sandbox: "off" });
  await page.reload();
  await page.locator(".new-chat-btn").click();

  // Bind a working directory to the new conversation through the API.
  const convs = await (await page.request.get(`${API}/api/conversations`)).json();
  const convId = (convs[0] ?? convs.conversations?.[0]).id;
  expect((await page.request.patch(`${API}/api/conversations/${convId}/workdir`, { data: { workdir } })).ok()).toBeTruthy();

  await page.locator(".mode-picker-btn").click();
  await page.getByRole("option", { name: /Agent/ }).click();
  await send(page, "Please create the e2e file");

  const approve = page.getByRole("button", { name: /^Approve$/ });
  await expect(approve).toBeVisible();
  expect(existsSync(join(workdir, "e2e.txt"))).toBe(false); // nothing ran before approval
  await approve.click();

  await expect(page.getByText("Wrote e2e.txt for you.")).toBeVisible();
  expect(readFileSync(join(workdir, "e2e.txt"), "utf8")).toBe("hello from e2e");
});

test("agent mode denial leaves the filesystem untouched", async ({ page }) => {
  const workdir = mkdtempSync(join(tmpdir(), "zenith-e2e-deny-"));
  await patchConfig(page, { agent_enabled: true, agent_mode: "manual", agent_sandbox: "off" });
  await page.reload();
  await page.locator(".new-chat-btn").click();
  const convs = await (await page.request.get(`${API}/api/conversations`)).json();
  const convId = (convs[0] ?? convs.conversations?.[0]).id;
  await page.request.patch(`${API}/api/conversations/${convId}/workdir`, { data: { workdir } });

  await page.locator(".mode-picker-btn").click();
  await page.getByRole("option", { name: /Agent/ }).click();
  await send(page, "Please create the e2e file");
  await page.getByRole("button", { name: /^Deny$/ }).click();
  await expect(page.getByText("Okay, I skipped writing the file.")).toBeVisible();
  expect(existsSync(join(workdir, "e2e.txt"))).toBe(false);
});

test("every settings section renders", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await page.getByRole("button", { name: "Settings" }).first().click();
  const nav = page.getByRole("navigation", { name: "Settings sections" });
  await expect(nav).toBeVisible();
  const items = nav.getByRole("button");
  const count = await items.count();
  expect(count).toBeGreaterThanOrEqual(18);
  for (let i = 0; i < count; i++) {
    const item = items.nth(i);
    const label = (await item.innerText()).trim();
    await item.click();
    await expect(page.locator(".settings-section").first(), `section "${label}"`).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("command palette opens and runs an action", async ({ page }) => {
  await page.keyboard.press("Control+k");
  const input = page.getByLabel("Search commands");
  await expect(input).toBeVisible();
  await input.fill("focus mode");
  await page.keyboard.press("Enter");
  await expect(page.locator(".app-shell-focus")).toBeVisible();
});

test("agent approval works from the keyboard (y)", async ({ page }) => {
  const workdir = mkdtempSync(join(tmpdir(), "zenith-e2e-key-"));
  await patchConfig(page, { agent_enabled: true, agent_mode: "manual", agent_sandbox: "off" });
  await page.reload();
  await page.locator(".new-chat-btn").click();
  const convs = await (await page.request.get(`${API}/api/conversations`)).json();
  const convId = (convs[0] ?? convs.conversations?.[0]).id;
  await page.request.patch(`${API}/api/conversations/${convId}/workdir`, { data: { workdir } });
  await page.locator(".mode-picker-btn").click();
  await page.getByRole("option", { name: /Agent/ }).click();
  await send(page, "Please create the e2e file");
  await expect(page.getByRole("button", { name: /^Approve$/ })).toBeVisible();
  await page.locator("textarea").first().blur();
  await page.keyboard.press("y");
  await expect(page.getByText("Wrote e2e.txt for you.")).toBeVisible();
  expect(readFileSync(join(workdir, "e2e.txt"), "utf8")).toBe("hello from e2e");
});

test("boot splash shows health checks once per session", async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.addInitScript(() => localStorage.setItem("zenith-onboarded", "1"));
  await page.goto("/");
  await expect(page.getByRole("status", { name: "Starting Zenith" })).toBeVisible();
  await expect(page.getByText("[ ok ]").first()).toBeVisible();
  await expect(page.locator(".new-chat-btn")).toBeVisible({ timeout: 5000 });
  await page.reload();
  await expect(page.locator(".new-chat-btn")).toBeVisible();
  await expect(page.getByRole("status", { name: "Starting Zenith" })).toHaveCount(0);
  await ctx.close();
});
