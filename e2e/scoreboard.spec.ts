import { expect, test } from "@playwright/test";
import {
  claimIds,
  createEvaluation,
  finishRun,
  payClaim,
  recordDecision,
  recordModelCall,
  recordWorkTime,
  startClaim,
  startedRuns,
  takeClaims,
} from "./api";

// This is the only file that creates evaluations. Its test plays one out
// through the API, standing in for the agent's service, on the evaluation
// set's five tiny claims. The handlers decided them: CLM-1007 approve $50,
// CLM-1015 decline, CLM-1017 refer, CLM-1020 approve $240 and CLM-1021
// approve $825.

const decision = (kind: string, payout: number) => ({
  decision: kind,
  payout,
  section: "Section 5, Baggage and Personal Effects",
  reason: `The agent's reason to ${kind}.`,
});

test("a handler starts an evaluation on the scoreboard", async ({
  page,
  request,
}) => {
  await page.goto("/scoreboard");
  const form = page.getByRole("form", { name: "Start an evaluation" });
  await form.getByRole("combobox", { name: "Set" }).selectOption("held_out");
  await form
    .getByRole("checkbox", { name: "Just the five tiny claims" })
    .check();
  await form
    .getByRole("spinbutton", { name: "Claim agents at once" })
    .fill("5");
  await form.getByRole("button", { name: "Start an evaluation" }).click();
  await expect(form.getByText("Evaluation started")).toBeVisible();
  expect(await startedRuns(request)).toContainEqual({
    kind: "evaluation",
    agents: 5,
    eval_set: "held_out",
    tiny: true,
  });
});

test("the scoreboard shows an evaluation played out through the API", async ({
  page,
  request,
}) => {
  const runId = await createEvaluation(request, "evaluation", true, 5);
  const copy = (claimId: string) => `${claimId}-${String(runId)}`;
  await takeClaims(request, runId, []);
  const answers: [string, string, number][] = [
    ["CLM-1007", "approve", 50], // right
    ["CLM-1015", "approve", 1350], // wrong decision, held for sign-off
    ["CLM-1017", "decline", 0], // wrong decision: a wrongful decline
    ["CLM-1020", "approve", 200], // wrong amount
  ];
  for (const [claimId, kind, payout] of answers) {
    await startClaim(request, copy(claimId), `e2e-${claimId}`);
    await recordDecision(request, copy(claimId), decision(kind, payout));
    await recordModelCall(request, copy(claimId), runId, 0.002);
    await recordWorkTime(request, copy(claimId), runId, 40);
  }
  await startClaim(request, copy("CLM-1021"), "e2e-CLM-1021"); // undecided
  expect((await payClaim(request, copy("CLM-1007"), 50)).ok()).toBe(true);
  expect((await payClaim(request, copy("CLM-1020"), 200)).ok()).toBe(true);
  await finishRun(request, runId);

  await page.goto("/scoreboard");
  const row = page
    .getByRole("region", { name: "Evaluations" })
    .getByRole("row")
    .filter({ hasText: `Evaluation ${String(runId)}` });
  await expect(row).toContainText("Evaluation set, just the tiny claims");
  await expect(row.locator("td")).toHaveText([
    `Evaluation ${String(runId)}`,
    /\d/,
    "Evaluation set, just the tiny claims",
    "5",
    "openai/gpt-6-luna (low)",
    "Finished",
    "5",
    "40%",
    "20%",
    "$2,940.00",
    "80%",
    "$0.0016",
    "32s",
    /^\d+s$/,
  ]);

  await row.getByRole("link").click();
  await expect(page).toHaveURL(`/evaluations/${String(runId)}`);
  const claims = page.getByRole("region", { name: "Claims" });
  await expect(claims.locator("tbody tr")).toHaveCount(5);
  await expect(claims.locator("tbody tr.miss")).toHaveCount(4);
  const claimRow = (claimId: string) =>
    claims.locator("tbody tr").filter({ hasText: copy(claimId) });
  await expect(claimRow("CLM-1007")).toContainText("Right");
  await expect(claimRow("CLM-1017")).toContainText("Wrong decision");
  await expect(claimRow("CLM-1020")).toContainText("Wrong amount");
  await expect(claimRow("CLM-1021")).toContainText(
    "No decision (counts as a referral)",
  );

  await claimRow("CLM-1015")
    .getByRole("link", { name: copy("CLM-1015") })
    .click();
  await expect(page).toHaveURL(`/claims/${copy("CLM-1015")}`);
  await expect(
    page.getByText(
      "Held for sign-off. An evaluation's copy is never signed off.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign off" })).toHaveCount(0);

  const queue = await claimIds(request);
  expect(queue).toHaveLength(25);
  expect(
    queue.filter((claimId) => claimId.endsWith(`-${String(runId)}`)),
  ).toEqual([]);
});
