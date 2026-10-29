"""The UnderCover backend's API: every call the agent makes to it, in one place."""

from typing import Any

import httpx

BACKEND_URL = "http://localhost:8000"


class ApiError(Exception):
    """The backend refused a request."""


def client() -> httpx.Client:
    """Return a client for the backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


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


def list_claims() -> list[dict[str, Any]]:
    """List every claim in the queue."""
    return call("GET", "/api/claims")


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
    """Get the agent's instructions for running the queue and for working a claim."""
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
    """Pay an approved claim its payout."""
    return call("POST", f"/api/claims/{claim_id}/payment", {"amount": amount})


def record_failure(claim_id: str, reason: str) -> dict[str, Any]:
    """Record a failed try on a claim in progress."""
    return call("POST", f"/api/claims/{claim_id}/failure", {"reason": reason})


def start_run(limit: int) -> dict[str, Any]:
    """Start a run of the agent over the queue, capped at limit claims."""
    return call("POST", "/api/runs", {"limit": limit})


def write_todos(run_id: int, todos: list[dict[str, str]]) -> dict[str, Any]:
    """Replace a run's to-do list."""
    return call("PUT", f"/api/runs/{run_id}/todos", {"todos": todos})


def finish_run(run_id: int, summary: str) -> dict[str, Any]:
    """Finish a run with a summary for the handlers."""
    return call("POST", f"/api/runs/{run_id}/finish", {"summary": summary})
