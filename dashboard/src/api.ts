export type Status =
  | "waiting"
  | "in_progress"
  | "waiting_for_sign_off"
  | "decided"
  | "left_for_handler";
export type DecisionKind = "approve" | "decline" | "refer";
export type StepKind =
  "tool_call" | "tool_result" | "message" | "read" | "error";

export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  claim_type: string;
  summary: string;
  amount_claimed: number;
  submitted_on: string;
  status: Status;
  decision: DecisionKind | null;
  payout: number | null;
}

export interface Item {
  description: string;
  category: string;
  amount: number;
}

export interface ClaimDocument {
  name: string;
  type: string;
  content: string;
}

export interface Decision {
  decision: DecisionKind;
  payout: number;
  section: string;
  reason: string;
  decided_at: string;
  signed_off_by: string | null;
  signed_off_at: string | null;
}

export interface Payment {
  amount: number;
  paid_at: string;
  signed_off_by: string | null;
  signed_off_at: string | null;
}

export interface Claim {
  claim_id: string;
  policy_id: string;
  customer_id: string;
  customer_name: string;
  claim_type: string;
  submitted_on: string;
  incident_date: string;
  incident_location: string;
  summary: string;
  story: string;
  items: Item[];
  amount_claimed: number;
  documents: ClaimDocument[];
  status: Status;
  thread_id: string | null;
  evaluation_id: number | null;
  decision: Decision | null;
  payment: Payment | null;
}

export interface Policy {
  policy_id: string;
  customer_id: string;
  plan: string;
  add_ons: string[];
  purchased_on: string;
  sold_through: string;
  trip: {
    destination: string;
    departs_on: string;
    returns_on: string;
    trip_cost: number;
  };
  travelers: string[];
  status: string;
}

export interface PreviousClaim {
  claim_id: string;
  filed_on: string;
  incident_date: string;
  claim_type: string;
  summary: string;
  outcome: string;
  amount_paid: number;
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
  can_approve_over_limit: boolean;
}

export interface Step {
  step_id: number;
  thread_id: string;
  kind: StepKind;
  content: string;
  created_at: string;
}

export interface Instructions {
  claim: string;
}

export type RunStatus = "running" | "finished" | "stopped";
export type Effort = "low" | "none";
export type EvalSet = "evaluation" | "held_out";

export interface Run {
  run_id: number;
  kind: "dispatch" | "evaluation";
  agents: number;
  model: string;
  reasoning_effort: Effort;
  eval_set: EvalSet | null;
  tiny: boolean | null;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
}

export interface RunClaim {
  claim_id: string;
  status: Status;
  decision: DecisionKind | null;
  payout: number | null;
  started_at: string | null;
  seconds: number;
  cost: number;
}

export interface HeldPayout {
  claim_id: string;
  payout: number;
}

export interface DispatchSummary {
  approved: number;
  declined: number;
  referred: number;
  waiting_for_sign_off: HeldPayout[];
  left_for_handler: string[];
  in_progress: string[];
}

export interface Dispatch extends Run {
  cost: number;
  run_seconds: number | null;
  work_seconds: number;
  claims: RunClaim[];
  summary: DispatchSummary | null;
}

export interface Measures {
  decision_accuracy: number;
  accuracy: number;
  cost_of_mistakes: number;
  straight_through: number;
  cost_per_claim: number;
  seconds_per_claim: number;
  run_seconds: number | null;
}

export interface ScoredClaim {
  claim_id: string;
  source_id: string;
  status: Status;
  handler_decision: DecisionKind;
  handler_payout: number;
  decision: DecisionKind | null;
  payout: number | null;
  reason: string | null;
  right_decision: boolean;
  right: boolean;
  mistake_cost: number;
  seconds: number;
  cost: number;
}

export interface EvaluationSummary extends Run {
  claim_count: number;
  measures: Measures;
}

export interface Evaluation extends EvaluationSummary {
  claims: ScoredClaim[];
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = (await response.json()) as { detail?: unknown };
    const detail =
      typeof body.detail === "string" ? body.detail : "The request failed";
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

function post<T>(path: string, body: object): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const claimPath = (claimId: string) =>
  `/api/claims/${encodeURIComponent(claimId)}`;

export const api = {
  listClaims: () => request<ClaimSummary[]>("/api/claims"),
  getClaim: (claimId: string) => request<Claim>(claimPath(claimId)),
  listSteps: (claimId: string) =>
    request<Step[]>(`${claimPath(claimId)}/steps`),
  getPolicy: (policyId: string) =>
    request<Policy>(`/api/policies/${encodeURIComponent(policyId)}`),
  getClaimHistory: (customerId: string) =>
    request<PreviousClaim[]>(
      `/api/customers/${encodeURIComponent(customerId)}/claims`,
    ),
  getInstructions: () => request<Instructions>("/api/instructions"),
  listHandlers: () => request<Handler[]>("/api/handlers"),
  getLatestDispatch: () => request<Dispatch | null>("/api/dispatches/latest"),
  startDispatch: (agents: number) =>
    post<{ status: string }>("/api/dispatches/start", { agents }),
  startEvaluation: (agents: number, evalSet: EvalSet, tiny: boolean) =>
    post<{ status: string }>("/api/evaluations/start", {
      agents,
      eval_set: evalSet,
      tiny,
    }),
  listEvaluations: () => request<EvaluationSummary[]>("/api/evaluations"),
  getEvaluation: (runId: number) =>
    request<Evaluation>(`/api/evaluations/${String(runId)}`),
  signOff: (claimId: string, handlerId: string) =>
    post<Claim>(`${claimPath(claimId)}/sign-off`, { handler_id: handlerId }),
};
