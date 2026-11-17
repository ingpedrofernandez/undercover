import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Dispatch, RunClaim } from "./api";
import { Refusal, stubApi, summary } from "./testing";

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
  eval_set: null,
  tiny: null,
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
  const fetchMock = stubApi(routes);
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
  return Object.assign(routes, { fetchMock });
}

const paid: RunClaim = {
  claim_id: "CLM-1001",
  status: "decided",
  decision: "approve",
  payout: 420,
  started_at: "2026-11-17T14:02:01+00:00",
  seconds: 75.4,
  cost: 0.0042,
};

const working: RunClaim = {
  claim_id: "CLM-1006",
  status: "in_progress",
  decision: null,
  payout: null,
  started_at: null,
  seconds: 0,
  cost: 0,
};

// Each claim's row as its cells' text.
function rows(panel: HTMLElement) {
  return [...panel.querySelectorAll("tbody tr")].map((row) =>
    [...row.querySelectorAll("td")].map((cell) => cell.textContent),
  );
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
      /^Dispatch 3, 5 claim agents at once, openai\/gpt-6-luna \(low\), started at .*\. Running now\.$/,
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

it("shows each of a running dispatch's claims, its cost and time", async () => {
  showQueue({ ...running, claims: [paid, working] });
  const element = await runPanel();
  const panel = within(element);
  expect(
    await panel.findByText(
      "Model cost $0.0123. The claims took 1m 35s of the agents' time in all.",
    ),
  ).toBeDefined();
  expect(panel.getByText(/openai\/gpt-6-luna \(low\)/)).toBeDefined();
  const [first, second] = rows(element);
  expect(first[0]).toBe("CLM-1001");
  expect(first.slice(1, 4)).toEqual(["Decided", "Approved", "$420.00"]);
  expect(first[4]).not.toBe("");
  expect(first.slice(5)).toEqual(["1m 15s", "$0.0042"]);
  expect(second.slice(0, 4)).toEqual(["CLM-1006", "In progress", "", ""]);
  expect(second.slice(4)).toEqual(["", "0s", "$0.0000"]);
  expect(panel.getByRole("link", { name: "CLM-1001" })).toHaveProperty(
    "href",
    expect.stringMatching(/\/claims\/CLM-1001$/),
  );
  expect(panel.queryByRole("heading", { name: "Summary" })).toBeNull();
});

it("sums up a finished dispatch from its records", async () => {
  showQueue({
    ...running,
    status: "finished",
    finished_at: "2026-11-17T14:05:12+00:00",
    run_seconds: 192,
    claims: [paid, working],
    summary: {
      approved: 2,
      declined: 1,
      referred: 1,
      waiting_for_sign_off: [{ claim_id: "CLM-1008", payout: 2240 }],
      left_for_handler: ["CLM-1015"],
      in_progress: [],
    },
  });
  const element = await runPanel();
  const panel = within(element);
  expect(await panel.findByText(/after 3m 12s\.$/)).toBeDefined();
  expect(panel.getByRole("heading", { name: "Summary" })).toBeDefined();
  expect(
    [...element.querySelectorAll(".summary li")].map(
      (item) => item.textContent,
    ),
  ).toEqual([
    "Approved 2, declined 1 and referred 1.",
    "Waiting for sign-off: CLM-1008 ($2,240.00).",
    "Left for a handler: CLM-1015.",
    "Still in progress: none.",
  ]);
});

it("starts a dispatch with the number of claim agents chosen", async () => {
  const routes = showQueue(null);
  routes["POST /api/dispatches/start"] = { status: "started" };
  const form = within(
    await screen.findByRole("form", { name: "Start a dispatch" }),
  );
  const agents = form.getByRole("spinbutton", { name: "Claim agents at once" });
  expect(agents).toHaveProperty("value", "3");
  expect(agents.getAttribute("min")).toBe("1");
  expect(agents.getAttribute("max")).toBe("25");

  fireEvent.change(agents, { target: { value: "5" } });
  fireEvent.click(form.getByRole("button", { name: "Start a dispatch" }));
  expect(await form.findByText("Dispatch started")).toBeDefined();
  const [, init] = routes.fetchMock.mock.calls.find(
    ([path]) => path === "/api/dispatches/start",
  ) ?? [undefined, undefined];
  expect(init?.method).toBe("POST");
  expect(init?.body).toBe(JSON.stringify({ agents: 5 }));
});

it.each([
  [409, "A dispatch or evaluation is already running"],
  [503, "The agent's service isn't running"],
])("says why a start was refused with %i", async (status, detail) => {
  const routes = showQueue(null);
  routes["POST /api/dispatches/start"] = new Refusal(status, detail);
  const form = within(
    await screen.findByRole("form", { name: "Start a dispatch" }),
  );
  fireEvent.click(form.getByRole("button", { name: "Start a dispatch" }));
  expect((await form.findByRole("alert")).textContent).toBe(detail);
  expect(form.queryByText("Dispatch started")).toBeNull();
});
