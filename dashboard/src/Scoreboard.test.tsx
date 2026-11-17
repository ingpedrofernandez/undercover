import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Evaluation, EvaluationSummary, ScoredClaim } from "./api";
import { Refusal, claim, stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const finished: EvaluationSummary = {
  run_id: 7,
  kind: "evaluation",
  agents: 25,
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  eval_set: "evaluation",
  tiny: false,
  status: "finished",
  started_at: "2026-11-17T14:02:00+00:00",
  finished_at: "2026-11-17T14:04:30+00:00",
  claim_count: 25,
  measures: {
    decision_accuracy: 0.84,
    accuracy: 0.6,
    cost_of_mistakes: 1890.4,
    straight_through: 0.88,
    cost_per_claim: 0.0031,
    seconds_per_claim: 62.4,
    run_seconds: 150,
  },
};

const stopped: EvaluationSummary = {
  ...finished,
  run_id: 8,
  eval_set: "held_out",
  tiny: true,
  agents: 5,
  status: "stopped",
  claim_count: 5,
  measures: { ...finished.measures, run_seconds: null },
};

const scored = (changes: Partial<ScoredClaim>): ScoredClaim => ({
  claim_id: "CLM-1007-7",
  source_id: "CLM-1007",
  status: "decided",
  handler_decision: "approve",
  handler_payout: 50,
  decision: "approve",
  payout: 50,
  reason: "The phone is covered.",
  right_decision: true,
  right: true,
  mistake_cost: 0,
  seconds: 61,
  cost: 0.0042,
  ...changes,
});

const evaluation: Evaluation = {
  ...finished,
  claims: [
    scored({}),
    scored({
      claim_id: "CLM-1015-7",
      source_id: "CLM-1015",
      status: "waiting_for_sign_off",
      handler_decision: "decline",
      handler_payout: 0,
      payout: 1350,
      right_decision: false,
      right: false,
      mistake_cost: 1350,
    }),
    scored({
      claim_id: "CLM-1020-7",
      source_id: "CLM-1020",
      handler_payout: 240,
      payout: 200,
      right: false,
      mistake_cost: 40,
    }),
    scored({
      claim_id: "CLM-1021-7",
      source_id: "CLM-1021",
      status: "in_progress",
      handler_payout: 825,
      decision: null,
      payout: null,
      reason: null,
      right_decision: false,
      right: false,
      mistake_cost: 50,
    }),
  ],
};

function renderAt(path: string, routes: Record<string, unknown>) {
  const fetchMock = stubApi(routes);
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return fetchMock;
}

function cells(row: HTMLElement) {
  return [...row.querySelectorAll("td")].map((cell) => cell.textContent);
}

it("lists the evaluations with every measure", async () => {
  renderAt("/scoreboard", { "GET /api/evaluations": [stopped, finished] });
  const table = within(
    await screen.findByRole("region", { name: "Evaluations" }),
  );
  const [header, first, second] = await table.findAllByRole("row");
  expect(
    within(header)
      .getAllByRole("columnheader")
      .map((h) => h.textContent),
  ).toEqual([
    "Evaluation",
    "Started",
    "Set",
    "Agents",
    "Model",
    "State",
    "Claims",
    "Decision accuracy",
    "Accuracy",
    "Cost of mistakes",
    "Straight-through",
    "Cost per claim",
    "Time per claim",
    "Run time",
  ]);
  const newest = cells(first);
  expect(newest[0]).toBe("Evaluation 8");
  expect(newest.slice(2)).toEqual([
    "Held-out set, just the tiny claims",
    "5",
    "openai/gpt-6-luna (low)",
    "Stopped",
    "5",
    "84%",
    "60%",
    "$1,890.40",
    "88%",
    "$0.0031",
    "1m 2s",
    "",
  ]);
  expect(cells(second).slice(2, 7)).toEqual([
    "Evaluation set",
    "25",
    "openai/gpt-6-luna (low)",
    "Finished",
    "25",
  ]);
  expect(cells(second).at(-1)).toBe("2m 30s");
  expect(table.getByRole("link", { name: "Evaluation 7" })).toHaveProperty(
    "href",
    expect.stringMatching(/\/evaluations\/7$/),
  );
});

it("says when there are no evaluations", async () => {
  renderAt("/scoreboard", { "GET /api/evaluations": [] });
  expect(await screen.findByText("No evaluations yet.")).toBeDefined();
});

it("starts an evaluation of the set chosen", async () => {
  const fetchMock = renderAt("/scoreboard", {
    "GET /api/evaluations": [],
    "POST /api/evaluations/start": { status: "started" },
  });
  const form = within(
    await screen.findByRole("form", { name: "Start an evaluation" }),
  );
  expect(
    form.getByRole("spinbutton", { name: "Claim agents at once" }),
  ).toHaveProperty("value", "3");
  fireEvent.change(form.getByRole("combobox", { name: "Set" }), {
    target: { value: "held_out" },
  });
  fireEvent.click(
    form.getByRole("checkbox", { name: "Just the five tiny claims" }),
  );
  fireEvent.change(
    form.getByRole("spinbutton", { name: "Claim agents at once" }),
    { target: { value: "5" } },
  );
  fireEvent.click(form.getByRole("button", { name: "Start an evaluation" }));
  expect(await form.findByText("Evaluation started")).toBeDefined();
  const [, init] = fetchMock.mock.calls.find(
    ([path]) => path === "/api/evaluations/start",
  ) ?? [undefined, undefined];
  expect(init?.body).toBe(
    JSON.stringify({ agents: 5, eval_set: "held_out", tiny: true }),
  );
});

it("says why an evaluation was refused", async () => {
  renderAt("/scoreboard", {
    "GET /api/evaluations": [],
    "POST /api/evaluations/start": new Refusal(
      409,
      "A dispatch or evaluation is already running",
    ),
  });
  const form = within(
    await screen.findByRole("form", { name: "Start an evaluation" }),
  );
  fireEvent.click(form.getByRole("button", { name: "Start an evaluation" }));
  expect((await form.findByRole("alert")).textContent).toBe(
    "A dispatch or evaluation is already running",
  );
});

it("shows an evaluation's claims beside the handlers' decisions", async () => {
  renderAt("/evaluations/7", { "GET /api/evaluations/7": evaluation });
  expect(
    await screen.findByRole("heading", { name: "Evaluation 7" }),
  ).toBeDefined();
  const measures = within(
    screen.getByRole("heading", { name: "Measures" }).closest("section") ??
      document.body,
  );
  expect(measures.getByText("84%")).toBeDefined();
  expect(measures.getByText("2m 30s")).toBeDefined();

  const table = within(screen.getByRole("region", { name: "Claims" }));
  const [, right, wrongDecision, wrongAmount, undecided] =
    table.getAllByRole("row");
  expect(cells(right).slice(0, 5)).toEqual([
    "CLM-1007-7",
    "CLM-1007",
    "Right",
    "Approved $50.00",
    "Approved $50.00",
  ]);
  expect(right.className).toBe("");
  expect(cells(wrongDecision).slice(2, 5)).toEqual([
    "Wrong decision",
    "Declined ",
    "Approved $1,350.00",
  ]);
  expect(wrongDecision.className).toBe("miss");
  expect(cells(wrongAmount)[2]).toBe("Wrong amount");
  expect(cells(wrongAmount).at(-3)).toBe("$40.00");
  expect(cells(undecided)[4]).toBe("No decision (counts as a referral)");
  expect(undecided.className).toBe("miss");
  expect(table.getByRole("link", { name: "CLM-1015-7" })).toHaveProperty(
    "href",
    expect.stringMatching(/\/claims\/CLM-1015-7$/),
  );
});

it("says when an evaluation isn't found", async () => {
  renderAt("/evaluations/99", {
    "GET /api/evaluations/99": new Refusal(404, "Evaluation 99 not found"),
  });
  expect(await screen.findByText("Evaluation not found")).toBeDefined();
});

it("shows a copy held for sign-off without the sign-off form", async () => {
  const copy = {
    ...claim,
    claim_id: "CLM-1015-7",
    evaluation_id: 7,
    status: "waiting_for_sign_off",
    thread_id: "t-1",
    decision: {
      decision: "approve",
      payout: 1350,
      section: "Section 5",
      reason: "Covered.",
      decided_at: "2026-11-17T14:03:00+00:00",
      signed_off_by: null,
      signed_off_at: null,
    },
  };
  renderAt("/claims/CLM-1015-7", {
    "GET /api/claims/CLM-1015-7": copy,
    "GET /api/claims/CLM-1015-7/steps": [],
    "GET /api/policies/POL-2002": null,
    "GET /api/customers/CUS-3002/claims": [],
    "GET /api/handlers": [],
  });
  expect(
    await screen.findByText(
      "Held for sign-off. An evaluation's copy is never signed off.",
    ),
  ).toBeDefined();
  expect(screen.queryByRole("button", { name: "Sign off" })).toBeNull();
  expect(screen.getByRole("link", { name: "evaluation 7" })).toHaveProperty(
    "href",
    expect.stringMatching(/\/evaluations\/7$/),
  );
});
