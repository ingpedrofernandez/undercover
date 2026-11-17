"""The UnderCover backend's API: every call the agent makes to it, in one place."""

from typing import Any

import httpx

BACKEND_URL = "http://127.0.0.1:8000"
CONNECT_RETRIES = 6


class ApiError(Exception):
    """The backend refused a request."""


def client() -> httpx.Client:
    """Return a client for the backend.

    It retries connecting for about 15 seconds, so the agent's service can start
    while the backend is still starting beside it.
    """
    transport = httpx.HTTPTransport(retries=CONNECT_RETRIES)
    return httpx.Client(base_url=BACKEND_URL, timeout=30, transport=transport)


def call(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    """Send one request and return its JSON, raising ApiError if the backend refuses."""
    with client() as backend:
        response = backend.request(method, path, json=body, params=params)
    if response.is_error:
        raise ApiError(f"{response.status_code}: {response.json()['detail']}")
    return response.json()


def get_claim(claim_id: str) -> dict[str, Any]:
    """Get one claim in full."""
    return call("GET", f"/api/claims/{claim_id}")


def get_policy(policy_id: str) -> dict[str, Any]:
    """Get a policy."""
    return call("GET", f"/api/policies/{policy_id}")


def get_claim_history(customer_id: str) -> list[dict[str, Any]]:
    """Get a customer's earlier claims."""
    return call("GET", f"/api/customers/{customer_id}/claims")


def get_instructions() -> dict[str, str]:
    """Get the claim agent's instructions for working a claim."""
    return call("GET", "/api/instructions")


def list_sections(document: str) -> list[dict[str, Any]]:
    """List the sections of the policy wording or the claims manual."""
    return call("GET", f"/api/documents/{document}/sections")


def search_documents(query: str) -> list[dict[str, Any]]:
    """Find the sections of either document with a line containing the query."""
    return call("GET", "/api/documents/search", params={"query": query})


def read_section(document: str, section: int) -> dict[str, Any]:
    """Read one section of the policy wording or the claims manual."""
    return call("GET", f"/api/documents/{document}/sections/{section}")


def start_claim(claim_id: str, thread_id: str) -> dict[str, Any]:
    """Start work on a waiting claim."""
    return call("POST", f"/api/claims/{claim_id}/start", {"thread_id": thread_id})


def record_step(claim_id: str, kind: str, content: str) -> dict[str, Any]:
    """Record one step of the agent's work on a claim."""
    body = {"kind": kind, "content": content}
    return call("POST", f"/api/claims/{claim_id}/steps", body)


def record_model_call(
    claim_id: str,
    run_id: int | None,
    input_tokens: int,
    output_tokens: int,
    cost: float,
) -> dict[str, Any]:
    """Record the tokens and cost of one model call made on a claim."""
    body = {
        "run_id": run_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
    }
    return call("POST", f"/api/claims/{claim_id}/model-calls", body)


def record_work_time(
    claim_id: str, run_id: int | None, started_at: str, seconds: float
) -> dict[str, Any]:
    """Record how long the agent worked on a claim in one piece of work."""
    body = {"run_id": run_id, "started_at": started_at, "seconds": seconds}
    return call("POST", f"/api/claims/{claim_id}/work-times", body)


def calculate_payout(
    policy_id: str, benefit: str, lines: list[dict[str, Any]], paid_by_others: float
) -> dict[str, Any]:
    """Work out the payout on an approved claim with UnderCover's payout rules."""
    body = {
        "policy_id": policy_id,
        "benefit": benefit,
        "lines": lines,
        "paid_by_others": paid_by_others,
    }
    return call("POST", "/api/payouts", body)


def record_decision(
    claim_id: str, decision: str, payout: float, section: str, reason: str
) -> dict[str, Any]:
    """Record the decision on a claim."""
    body = {
        "decision": decision,
        "payout": payout,
        "section": section,
        "reason": reason,
    }
    return call("POST", f"/api/claims/{claim_id}/decision", body)


def pay_claim(claim_id: str, amount: float) -> dict[str, Any]:
    """Pay an approved claim its payout, and return the claim."""
    return call("POST", f"/api/claims/{claim_id}/payment", {"amount": amount})


def record_failure(claim_id: str, reason: str) -> dict[str, Any]:
    """Record a failed try on a claim in progress."""
    return call("POST", f"/api/claims/{claim_id}/failure", {"reason": reason})


def create_dispatch(agents: int, model: str, reasoning_effort: str) -> dict[str, Any]:
    """Record a new dispatch over the queue, with agents claim agents at once."""
    body = {"agents": agents, "model": model, "reasoning_effort": reasoning_effort}
    return call("POST", "/api/dispatches", body)


def create_evaluation(
    agents: int, eval_set: str, tiny: bool, model: str, reasoning_effort: str
) -> dict[str, Any]:
    """Record a new evaluation of a labelled set, with a copy of each of its claims."""
    body = {
        "agents": agents,
        "eval_set": eval_set,
        "tiny": tiny,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }
    return call("POST", "/api/evaluations", body)


def take_claims(run_id: int, skip: list[str]) -> list[str]:
    """Pick the claims a run works, oldest submitted first, leaving out skip."""
    return call("POST", f"/api/runs/{run_id}/claims", {"skip": skip})


def finish_run(run_id: int) -> dict[str, Any]:
    """Finish a run that is still running."""
    return call("POST", f"/api/runs/{run_id}/finish")


def stop_runs() -> list[dict[str, Any]]:
    """Mark every run still running as stopped, and return them."""
    return call("POST", "/api/runs/stop")
