import { type APIRequestContext, expect, test } from "@playwright/test";

// This test stands in for the queue agent by calling the API through the
// dashboard's proxy. It is the only test that starts runs.

async function call(
  request: APIRequestContext,
  method: "post" | "put",
  path: string,
  data: object,
) {
  const response = await request[method](path, { data });
  expect(response.ok()).toBe(true);
}

const todos = (statuses: string[]) =>
  ["Work CLM-1006", "Work CLM-1007", "Write the summary"].map(
    (content, index) => ({ content, status: statuses[index] }),
  );

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

  await call(request, "post", "/api/runs", { limit: 2 });
  await call(request, "put", "/api/runs/1/todos", {
    todos: todos(["in_progress", "to_do", "to_do"]),
  });
  await expect(
    panel.getByText(/capped at 2 claims\. Running now\./),
  ).toBeVisible();
  const items = panel.getByRole("listitem");
  await expect(items).toHaveText([
    "In progressWork CLM-1006",
    "To doWork CLM-1007",
    "To doWrite the summary",
  ]);

  await call(request, "put", "/api/runs/1/todos", {
    todos: todos(["done", "left_for_handler", "in_progress"]),
  });
  await expect(items).toHaveText([
    "DoneWork CLM-1006",
    "Left for a handlerWork CLM-1007",
    "In progressWrite the summary",
  ]);

  await call(request, "put", "/api/runs/1/todos", {
    todos: todos(["done", "left_for_handler", "done"]),
  });
  await call(request, "post", "/api/runs/1/finish", {
    summary:
      "Decided CLM-1006. CLM-1007 failed twice and is left for a handler.",
  });
  await expect(
    panel.getByText(
      "Decided CLM-1006. CLM-1007 failed twice and is left for a handler.",
    ),
  ).toBeVisible();
  await expect(panel.getByText(/Finished at/)).toBeVisible();
});
