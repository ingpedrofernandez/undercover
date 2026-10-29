import { act, cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Run } from "./api";
import { stubApi, summary } from "./testing";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const running: Run = {
  run_id: 3,
  limit: 5,
  started_at: "2026-10-29T14:02:00+00:00",
  finished_at: null,
  summary: null,
  todos: [
    { content: "Work CLM-1001", status: "done" },
    { content: "Work CLM-1002", status: "in_progress" },
    { content: "Work CLM-1003", status: "to_do" },
    { content: "Work CLM-1004", status: "left_for_handler" },
  ],
};

function showQueue(run: Run | null) {
  const routes: Record<string, unknown> = {
    "GET /api/claims": [summary],
    "GET /api/runs/latest": run,
  };
  stubApi(routes);
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  return routes;
}

async function runPanel(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", {
    name: "The agent's to-do list",
  });
  const panel = heading.closest("section");
  if (!panel) throw new Error("The heading has no panel");
  return panel;
}

// Each to-do item as its chip's class and its text.
function items(panel: HTMLElement) {
  return [...panel.querySelectorAll("li")].map((item) => [
    item.querySelector(".chip")?.className,
    item.textContent,
  ]);
}

it("says when the agent hasn't worked the queue", async () => {
  showQueue(null);
  const panel = within(await runPanel());
  expect(
    await panel.findByText("The agent hasn't worked the queue yet."),
  ).toBeDefined();
});

it("shows the to-do list of a run in progress", async () => {
  showQueue(running);
  const element = await runPanel();
  const panel = within(element);
  expect(
    await panel.findByText(/capped at 5 claims\. Running now\./),
  ).toBeDefined();
  expect(panel.getByText(/^Run 3, started at/)).toBeDefined();
  expect(items(element)).toEqual([
    ["chip todo-done", "DoneWork CLM-1001"],
    ["chip todo-in_progress", "In progressWork CLM-1002"],
    ["chip todo-to_do", "To doWork CLM-1003"],
    ["chip todo-left_for_handler", "Left for a handlerWork CLM-1004"],
  ]);
  expect(panel.queryByText("Summary")).toBeNull();
});

it("shows a finished run with its summary", async () => {
  showQueue({
    ...running,
    limit: 1,
    todos: [],
    finished_at: "2026-10-29T14:09:00+00:00",
    summary: "Worked 1 claim: 1 approve.",
  });
  const panel = within(await runPanel());
  expect(await panel.findByText("Worked 1 claim: 1 approve.")).toBeDefined();
  expect(panel.getByText(/capped at 1 claim\. Finished at/)).toBeDefined();
  expect(panel.getByText("No items yet.")).toBeDefined();
  expect(panel.getByRole("heading", { name: "Summary" })).toBeDefined();
});

it("ticks items off as the run goes on", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const routes = showQueue({ ...running, todos: [] });
  const element = await runPanel();
  expect(await within(element).findByText("No items yet.")).toBeDefined();

  routes["GET /api/runs/latest"] = running;
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(items(element)[1][1]).toBe("In progressWork CLM-1002");

  routes["GET /api/runs/latest"] = {
    ...running,
    todos: running.todos.map((todo) => ({ ...todo, status: "done" })),
  };
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(items(element)[1][1]).toBe("DoneWork CLM-1002");
});
