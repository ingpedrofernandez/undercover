import { expect, test } from "@playwright/test";
import { finishRun, startRun, writeTodos } from "./api";

// This is the only test that starts runs.

const todos = (statuses: string[]) =>
  ["Work CLM-1006", "Work CLM-1007", "Write the summary"].map(
    (content, index) => ({ content, status: statuses[index] }),
  );

const summary =
  "Decided CLM-1006. CLM-1007 failed twice and is left for a handler.";

test("the queue page shows the agent's to-do list", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const panel = page.locator("section", {
    has: page.getByRole("heading", { name: "The agent's to-do list" }),
  });
  await expect(
    panel.getByText("The agent hasn't worked the queue yet."),
  ).toBeVisible();

  const runId = await startRun(request, 2);
  await writeTodos(request, runId, todos(["in_progress", "to_do", "to_do"]));
  await expect(
    panel.getByText(/capped at 2 claims\. Running now\./),
  ).toBeVisible();
  const items = panel.getByRole("listitem");
  await expect(items).toHaveText([
    "In progressWork CLM-1006",
    "To doWork CLM-1007",
    "To doWrite the summary",
  ]);

  await writeTodos(
    request,
    runId,
    todos(["done", "left_for_handler", "in_progress"]),
  );
  await expect(items).toHaveText([
    "DoneWork CLM-1006",
    "Left for a handlerWork CLM-1007",
    "In progressWrite the summary",
  ]);

  await writeTodos(request, runId, todos(["done", "left_for_handler", "done"]));
  await finishRun(request, runId, summary);
  await expect(panel.getByText(summary)).toBeVisible();
  await expect(panel.getByText(/Finished at/)).toBeVisible();
});
