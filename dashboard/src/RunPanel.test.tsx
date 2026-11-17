import { act, cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Dispatch } from "./api";
import { stubApi, summary } from "./testing";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const running: Dispatch = {
  run_id: 3,
  kind: "dispatch",
  agents: 5,
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  status: "running",
  started_at: "2026-11-17T14:02:00+00:00",
  finished_at: null,
  cost: 0.0123,
  run_seconds: null,
  work_seconds: 95,
  claims: [],
  summary: null,
};

function showQueue(dispatch: Dispatch | null) {
  const routes: Record<string, unknown> = {
    "GET /api/claims": [summary],
    "GET /api/dispatches/latest": dispatch,
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
  const heading = await screen.findByRole("heading", { name: "Dispatch" });
  const panel = heading.closest("section");
  if (!panel) throw new Error("The heading has no panel");
  return panel;
}

it("says when there has been no dispatch", async () => {
  showQueue(null);
  const panel = within(await runPanel());
  expect(await panel.findByText("No dispatch yet.")).toBeDefined();
});

it("shows a dispatch running", async () => {
  showQueue(running);
  const panel = within(await runPanel());
  expect(
    await panel.findByText(
      /^Dispatch 3, 5 claim agents at once, started at .*\. Running now\.$/,
    ),
  ).toBeDefined();
});

it("shows a finished and a stopped dispatch", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const routes = showQueue({
    ...running,
    agents: 1,
    status: "finished",
    finished_at: "2026-11-17T14:09:00+00:00",
  });
  const panel = within(await runPanel());
  expect(
    await panel.findByText(/1 claim agent at once, .* Finished at .*\.$/),
  ).toBeDefined();

  routes["GET /api/dispatches/latest"] = { ...running, status: "stopped" };
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(panel.getByText(/Stopped before it finished\.$/)).toBeDefined();
});
