import { expect, test } from "@playwright/test";
import {
  payClaim,
  recordDecision,
  recordFailure,
  recordStep,
  startClaim,
} from "./api";

// These tests watch the claim page update without a reload.

test("the claim page shows the agent at work", async ({ page, request }) => {
  await page.goto("/claims/CLM-1003");
  const heading = page.locator(".claim-heading");
  await expect(heading.getByText("Waiting")).toBeVisible();
  await expect(page.getByText(/No steps yet/)).toBeVisible();

  await startClaim(request, "CLM-1003", "e2e-1");
  await recordStep(
    request,
    "CLM-1003",
    "tool_call",
    'get_claim(claim_id="CLM-1003")',
  );
  await recordStep(
    request,
    "CLM-1003",
    "tool_result",
    'get_claim: {"claim_id":"CLM-1003"}',
  );
  await expect(heading.getByText("In progress")).toBeVisible();
  await expect(
    page.getByText("The agent is working on this claim."),
  ).toBeVisible();
  await expect(page.getByText('get_claim(claim_id="CLM-1003")')).toBeVisible();
  await expect(
    page.getByText('get_claim: {"claim_id":"CLM-1003"}').first(),
  ).toBeVisible();

  await recordDecision(request, "CLM-1003", {
    decision: "approve",
    payout: 500,
    section: "Section 7, Emergency Medical",
    reason: "The treatment was necessary and covered.",
  });
  expect((await payClaim(request, "CLM-1003", 500)).ok()).toBe(true);
  await recordStep(
    request,
    "CLM-1003",
    "message",
    "Approved and paid $500.00.",
  );
  await expect(heading.getByText("Decided")).toBeVisible();
  const decision = page.locator("section", {
    has: page.getByRole("heading", { name: "Decision" }),
  });
  await expect(decision.getByText("Approved")).toBeVisible();
  await expect(decision.getByText("Paid $500.00")).toBeVisible();
  await expect(page.getByText("Approved and paid $500.00.")).toBeVisible();
});

test("the claim page shows what the agent read", async ({ page, request }) => {
  await page.goto("/claims/CLM-1005");
  const reads = page.locator("section", {
    has: page.getByRole("heading", { name: "What the agent read" }),
  });
  await expect(reads.getByText(/Nothing yet/)).toBeVisible();

  await startClaim(request, "CLM-1005", "e2e-3");
  await recordStep(
    request,
    "CLM-1005",
    "read",
    "Claims manual, section 7: Interpretation notes\n\n## 7. Interpretation notes",
  );
  await expect(
    reads.getByText("Claims manual, section 7: Interpretation notes"),
  ).toBeVisible();
});

test("a claim that fails twice is left for a handler", async ({
  page,
  request,
}) => {
  await page.goto("/claims/CLM-1015");
  const heading = page.locator(".claim-heading");
  await expect(heading.getByText("Waiting")).toBeVisible();

  for (const [thread, reason] of [
    ["e2e-4", "The model timed out"],
    ["e2e-5", "The model is unavailable"],
  ]) {
    await startClaim(request, "CLM-1015", thread);
    await recordFailure(request, "CLM-1015", reason);
  }
  await expect(heading.getByText("Left for a handler")).toBeVisible();
  await expect(
    page.getByText("The model timed out. Back in the queue."),
  ).toBeVisible();
  await expect(
    page.getByText("The model is unavailable. Left for a handler."),
  ).toBeVisible();
});

test("a handler signs off a payout over the limit", async ({
  page,
  request,
}) => {
  await startClaim(request, "CLM-1020", "e2e-2");
  await recordDecision(request, "CLM-1020", {
    decision: "approve",
    payout: 1350,
    section: "Section 5, Baggage and Personal Effects",
    reason: "The loss is covered.",
  });
  expect((await payClaim(request, "CLM-1020", 1350)).status()).toBe(403);

  await page.goto("/claims/CLM-1020");
  await expect(
    page.locator(".claim-heading").getByText("Waiting for sign-off"),
  ).toBeVisible();
  await page.getByRole("combobox", { name: "Handler" }).selectOption({
    label: "Dana Whitfield",
  });
  await page.getByRole("button", { name: "Sign off" }).click();
  await expect(
    page.locator(".claim-heading").getByText("Decided"),
  ).toBeVisible();
  await expect(
    page.getByText("Paid $1,350.00, signed off by Dana Whitfield"),
  ).toBeVisible();
});
