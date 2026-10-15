import { test, expect } from "@playwright/test";
import { copyFileSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const file = resolve(".e2e/workspace.json");
const state = () => JSON.parse(readFileSync(file, "utf8"));
test.beforeEach(async ({ page }) => {
  copyFileSync(resolve("../fixtures/starter.json"), file);
  await page.route(/^https?:/, route => ["127.0.0.1", "localhost"].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
});

test("production chat runs native read/proposal tools and commits only after operator approval", async ({ page }, testInfo) => {
  await page.goto("/");
  const input = page.locator(".chat-wrap textarea");
  await input.fill("Inspect case-104 and propose the damaged scanner refund.");
  await input.press("Enter");
  await expect(page.locator(".chat-wrap")).toContainText("no refund has been issued");
  await expect(page.getByRole("button", { name: "Approve refund" })).toBeEnabled();
  expect(state().orders[0].refunded_cents).toBe(0);
  expect(state().refunds).toEqual([]);
  expect(state().provider_observations).toHaveLength(3);
  expect(state().agent_observations.every((item: { accepted: boolean }) => item.accepted)).toBe(true);
  await page.getByRole("button", { name: "Approve refund" }).click();
  await expect(page.getByText("Refund refund-001 recorded for $29.99.")).toBeVisible();
  expect(state().refunds).toHaveLength(1);
  await page.screenshot({ path: testInfo.outputPath("native-chat-approved-state.png"), fullPage: true });
});

test("provider and unfinished-stream errors remain visible and a later chat turn recovers", async ({ page }) => {
  await page.goto("/");
  const input = page.locator(".chat-wrap textarea");
  await input.fill("Simulate provider outage for case-104.");
  await input.press("Enter");
  await expect(page.locator(".chat-wrap")).toContainText(/could not complete this request/i);
  expect(state().cases[0].proposal).toBeNull();
  expect(state().refunds).toEqual([]);
  await input.fill("Simulate an unfinished response for case-104.");
  await input.press("Enter");
  await expect.poll(() => state().agent_observations?.length ?? 0).toBe(1);
  await expect(page.locator(".chat-wrap")).toContainText(/could not complete this request/i);
  expect(state().cases[0].proposal).toBeNull();
  await input.fill("Inspect case-104 again and prepare a complete proposal.");
  await input.press("Enter");
  await expect(page.locator(".chat-wrap")).toContainText("no refund has been issued");
  await expect(page.getByRole("button", { name: "Approve refund" })).toBeEnabled();
  await expect(page.locator(".chat-wrap [role='alert']")).toHaveCount(0);
  expect(state().provider_observations).toHaveLength(5);
  expect(state().refunds).toEqual([]);
});
