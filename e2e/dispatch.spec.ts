import { expect, test } from "@playwright/test";
import {
  claimIds,
  createDispatch,
  finishRun,
  recordDecision,
  recordModelCall,
  recordWorkTime,
  startClaim,
  startedRuns,
  takeClaims,
} from "./api";

// This is the only file that creates dispatches. Its test plays one out
// through the API, standing in for the agent's service, on two claims no other
// test uses.

test("a handler starts a dispatch on the queue page", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const form = page.getByRole("form", { name: "Start a dispatch" });
  const agents = form.getByRole("spinbutton", { name: "Claim agents at once" });
  await expect(agents).toHaveValue("3");
  await agents.fill("5");
  await form.getByRole("button", { name: "Start a dispatch" }).click();
  await expect(form.getByText("Dispatch started")).toBeVisible();
  expect(await startedRuns(request)).toContainEqual({
    kind: "dispatch",
    agents: 5,
  });
});

test("the queue page shows a dispatch's claims, cost, time and summary", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const panel = page.locator("section", {
    has: page.getByRole("heading", { name: "Dispatch" }),
  });
  await expect(panel.getByText("No dispatch yet.")).toBeVisible();

  const two = ["CLM-1006", "CLM-1007"];
  const runId = await createDispatch(request, 3);
  const others = (await claimIds(request)).filter((id) => !two.includes(id));
  await takeClaims(request, runId, others);
  await expect(panel.getByText(/3 claim agents at once/)).toBeVisible();
  await expect(panel.getByText(/Running now\./)).toBeVisible();
  const rows = panel.locator("tbody tr");
  await expect(rows).toHaveCount(2);

  await startClaim(request, "CLM-1006", "e2e-d1");
  await startClaim(request, "CLM-1007", "e2e-d2");
  await recordModelCall(request, "CLM-1006", runId, 0.0042);
  await recordWorkTime(request, "CLM-1006", runId, 75);
  await recordModelCall(request, "CLM-1007", runId, 0.0021);
  await recordWorkTime(request, "CLM-1007", runId, 30);
  await recordDecision(request, "CLM-1006", {
    decision: "decline",
    payout: 0,
    section: "Section 9, General exclusions",
    reason: "The loss is excluded.",
  });
  const row = (claimId: string) => rows.filter({ hasText: claimId });
  await expect(row("CLM-1006")).toContainText("Decided");
  await expect(row("CLM-1006")).toContainText("Declined");
  await expect(row("CLM-1006")).toContainText("$0.0042");
  await expect(row("CLM-1007")).toContainText("In progress");
  await expect(
    panel.getByText(
      "Model cost $0.0063. The claims took 1m 45s of the agents' time in all.",
    ),
  ).toBeVisible();

  await finishRun(request, runId);
  await expect(panel.getByText(/Finished at .*, after \d+s\./)).toBeVisible();
  await expect(panel.locator(".summary li")).toHaveText([
    "Approved 0, declined 1 and referred 0.",
    "Waiting for sign-off: none.",
    "Left for a handler: none.",
    "Still in progress: CLM-1007.",
  ]);
  await row("CLM-1006").getByRole("link", { name: "CLM-1006" }).click();
  await expect(page).toHaveURL("/claims/CLM-1006");
});
