import {
  type APIRequestContext,
  type APIResponse,
  expect,
} from "@playwright/test";

// The tests stand in for the agent by calling the backend through the
// dashboard's proxy. Every call they make is here, and each must succeed,
// apart from payClaim, whose refusal a test checks. resumedClaims and
// startedRuns read what the stand-in for the agent's service was asked to do.

const AGENT_STAND_IN = "http://127.0.0.1:8003";

type Request = APIRequestContext;

async function succeeds(response: Promise<APIResponse>): Promise<APIResponse> {
  const done = await response;
  expect(done.ok()).toBe(true);
  return done;
}

export const startClaim = (
  request: Request,
  claimId: string,
  threadId: string,
) =>
  succeeds(
    request.post(`/api/claims/${claimId}/start`, {
      data: { thread_id: threadId },
    }),
  );

export const recordStep = (
  request: Request,
  claimId: string,
  kind: string,
  content: string,
) =>
  succeeds(
    request.post(`/api/claims/${claimId}/steps`, { data: { kind, content } }),
  );

export const recordDecision = (
  request: Request,
  claimId: string,
  decision: {
    decision: string;
    payout: number;
    section: string;
    reason: string;
  },
) =>
  succeeds(request.post(`/api/claims/${claimId}/decision`, { data: decision }));

export const payClaim = (request: Request, claimId: string, amount: number) =>
  request.post(`/api/claims/${claimId}/payment`, { data: { amount } });

export const recordFailure = (
  request: Request,
  claimId: string,
  reason: string,
) =>
  succeeds(
    request.post(`/api/claims/${claimId}/failure`, { data: { reason } }),
  );

export async function resumedClaims(request: Request): Promise<string[]> {
  const response = await succeeds(request.get(`${AGENT_STAND_IN}/resumed`));
  return (await response.json()) as string[];
}

export async function startedRuns(
  request: Request,
): Promise<Record<string, unknown>[]> {
  const response = await succeeds(request.get(`${AGENT_STAND_IN}/started`));
  return (await response.json()) as Record<string, unknown>[];
}

export async function claimIds(request: Request): Promise<string[]> {
  const response = await succeeds(request.get("/api/claims"));
  const claims = (await response.json()) as { claim_id: string }[];
  return claims.map((claim) => claim.claim_id);
}

export async function createDispatch(request: Request, agents: number) {
  const response = await succeeds(
    request.post("/api/dispatches", {
      data: { agents, model: "openai/gpt-6-luna", reasoning_effort: "low" },
    }),
  );
  return ((await response.json()) as { run_id: number }).run_id;
}

export const takeClaims = (request: Request, runId: number, skip: string[]) =>
  succeeds(
    request.post(`/api/runs/${String(runId)}/claims`, { data: { skip } }),
  );

export const recordModelCall = (
  request: Request,
  claimId: string,
  runId: number,
  cost: number,
) =>
  succeeds(
    request.post(`/api/claims/${claimId}/model-calls`, {
      data: { run_id: runId, input_tokens: 1200, output_tokens: 80, cost },
    }),
  );

export const recordWorkTime = (
  request: Request,
  claimId: string,
  runId: number,
  seconds: number,
) =>
  succeeds(
    request.post(`/api/claims/${claimId}/work-times`, {
      data: { run_id: runId, started_at: new Date().toISOString(), seconds },
    }),
  );

export const finishRun = (request: Request, runId: number) =>
  succeeds(request.post(`/api/runs/${String(runId)}/finish`));
