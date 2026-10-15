import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const statePath = resolve(".e2e/workspace.json");
const fixture = resolve("../fixtures/starter.json");
const readState = () => JSON.parse(readFileSync(statePath, "utf8"));

test.beforeEach(() => {
  const data = JSON.parse(readFileSync(fixture, "utf8"));
  for (const item of data.cases) {
    if (item.id === "case-104" || item.id === "case-106") {
      const order = data.orders.find((record: { id: string }) => record.id === item.order_id);
      item.proposal = { amount_cents: item.id === "case-104" ? 2999 : 1000, currency: "USD", reason: "Seeded offline browser proposal",
        binding: { order_id: order.id, customer_email: order.customer_email.toLowerCase(), currency: order.currency } };
      item.revision += 1;
    }
  }
  writeFileSync(statePath, JSON.stringify(data));
});

test("approval displays the exact committed refund and cannot be repeated", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Approve refund" })).toBeEnabled();
  expect(readState().refunds).toEqual([]);
  await page.getByRole("button", { name: "Approve refund" }).click();
  await expect(page.getByText("Refund refund-001 recorded for $29.99.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve refund" })).toBeDisabled();
  const state = readState();
  expect(state.orders.find((item: { id: string }) => item.id === "order-104").refunded_cents).toBe(2999);
  expect(state.refunds).toHaveLength(1);
  expect(state.refunds[0].amount_cents).toBe(2999);
  await page.reload();
  await expect(page.getByText("Refund refund-001 recorded for $29.99.")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("approved-refund.png"), fullPage: true });
});

test("rejection remains visible after reload and changes no payment", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Reject proposal" }).click();
  await expect(page.getByText("Proposal rejected. No refund was recorded.")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Proposal rejected. No refund was recorded.")).toBeVisible();
  expect(readState().refunds).toEqual([]);
  expect(readState().orders.every((item: { refunded_cents: number }) => item.refunded_cents === 0)).toBe(true);
});

test("an ineligible order keeps its conflict visible after refreshing records", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Replacement request/ }).click();
  await expect(page.getByRole("heading", { name: "Replacement request", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Approve refund" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "order does not qualify for a refund" })).toBeVisible();
  expect(readState().refunds).toEqual([]);
  await expect(page.getByText("COMMITTED RESULT")).toHaveCount(0);
});

test("a stale approval shows a conflict and reloads the changed proposal", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Approve refund" })).toBeEnabled();
  await page.route("**/cases/case-104/decision", async route => {
    const state = readState(); const current = state.cases.find((item: { id: string }) => item.id === "case-104");
    current.revision += 1; current.proposal.reason = "Updated while the operator reviewed";
    writeFileSync(statePath, JSON.stringify(state));
    await route.continue();
  });
  await page.getByRole("button", { name: "Approve refund" }).click();
  await expect(page.getByText("Updated while the operator reviewed")).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "case changed; reload before deciding" })).toBeVisible();
  expect(readState().refunds).toEqual([]);
});

test("a changed order currency cannot commit the operator's earlier USD proposal", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Approve refund" })).toBeEnabled();
  await page.route("**/cases/case-104/decision", async route => {
    const state = readState();
    state.orders.find((item: { id: string }) => item.id === "order-104").currency = "CAD";
    writeFileSync(statePath, JSON.stringify(state));
    await route.continue();
  });
  await page.getByRole("button", { name: "Approve refund" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "create a fresh proposal" })).toBeVisible();
  expect(readState().refunds).toEqual([]);
  expect(readState().orders.find((item: { id: string }) => item.id === "order-104").refunded_cents).toBe(0);
  await expect(page.getByText("COMMITTED RESULT")).toHaveCount(0);
});

test("a delayed read from the previous case cannot replace the selected case", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Damaged scanner shipment", exact: true })).toBeVisible();
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let received!: () => void;
  const started = new Promise<void>(resolve => { received = resolve; });
  let delivered!: () => void;
  const finished = new Promise<void>(resolve => { delivered = resolve; });
  await page.route("**/cases/case-104", async route => {
    const old = await route.fetch(); received();
    await held;
    await route.fulfill({ response: old }).catch(() => {}); delivered();
  });
  await started;
  await page.getByRole("button", { name: /Duplicate charge question/ }).click();
  await expect(page.getByRole("heading", { name: "Duplicate charge question", exact: true })).toBeVisible();
  release();
  await finished;
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByRole("heading", { name: "Duplicate charge question", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Damaged scanner shipment", exact: true })).toHaveCount(0);
});
