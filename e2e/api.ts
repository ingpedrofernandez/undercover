import {
  type APIRequestContext,
  type APIResponse,
  expect,
} from "@playwright/test";

// The tests stand in for the agent by calling the backend through the
// dashboard's proxy. Every call they make is here, and each must succeed,
// apart from payClaim, whose refusal a test checks. resumedClaims reads what
// the stand-in for the agent's service was asked to resume.

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
