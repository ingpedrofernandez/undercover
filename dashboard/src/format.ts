import type {
  DecisionKind,
  EvalSet,
  Measures,
  Run,
  RunStatus,
  Status,
} from "./api";

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const day = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

const clock = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

const cents = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

export function money(amount: number): string {
  return dollars.format(amount);
}

// What a model costs, to a hundredth of a cent, as small costs need.
export function cost(amount: number): string {
  return cents.format(amount);
}

export function percent(share: number): string {
  return `${String(Math.round(share * 100))}%`;
}

export function duration(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return minutes ? `${String(minutes)}m ${String(rest)}s` : `${String(rest)}s`;
}

export function date(isoDate: string): string {
  return day.format(new Date(`${isoDate}T00:00:00Z`));
}

export function time(isoTime: string): string {
  return clock.format(new Date(isoTime));
}

export function label(code: string): string {
  const words = code.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const statusLabels: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  waiting_for_sign_off: "Waiting for sign-off",
  decided: "Decided",
  left_for_handler: "Left for a handler",
};

export const runStatusLabels: Record<RunStatus, string> = {
  running: "Running",
  finished: "Finished",
  stopped: "Stopped",
};

export const setLabels: Record<EvalSet, string> = {
  evaluation: "Evaluation set",
  held_out: "Held-out set",
};

// The set an evaluation worked, and whether just its tiny claims.
export function setName(run: Run): string {
  const set = run.eval_set ? setLabels[run.eval_set] : "";
  return run.tiny ? `${set}, just the tiny claims` : set;
}

// The scoreboard's measures, each with its heading, in the order shown.
export const measureColumns: [string, (measures: Measures) => string][] = [
  ["Decision accuracy", (m) => percent(m.decision_accuracy)],
  ["Accuracy", (m) => percent(m.accuracy)],
  ["Cost of mistakes", (m) => money(m.cost_of_mistakes)],
  ["Straight-through", (m) => percent(m.straight_through)],
  ["Cost per claim", (m) => cost(m.cost_per_claim)],
  ["Time per claim", (m) => duration(m.seconds_per_claim)],
  ["Run time", (m) => (m.run_seconds === null ? "" : duration(m.run_seconds))],
];

export const decisionLabels: Record<DecisionKind, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};

const addOnNames: Record<string, string> = {
  adventure_sports: "Adventure Sports",
  pre_existing_waiver: "Pre-Existing Condition Waiver",
  electronics_plus: "Electronics Plus",
};

export function addOnName(code: string): string {
  return addOnNames[code] ?? label(code);
}

export function firstLine(text: string): string {
  return text.split("\n", 1)[0];
}
