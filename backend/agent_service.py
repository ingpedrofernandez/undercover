"""The backend's one client for the agent's service."""

import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException

AGENT_URL = "http://127.0.0.1:8002"

logger = logging.getLogger(__name__)


def client() -> httpx.Client:
    """Return a client for the agent's service, at UNDERCOVER_AGENT or port 8002."""
    return httpx.Client(base_url=os.getenv("UNDERCOVER_AGENT", AGENT_URL), timeout=10)


def resume_claim(claim_id: str) -> None:
    """Ask the agent's service to pick a claim back up.

    A sign-off stands whether or not the service hears about it: the next
    dispatch carries on every claim in progress. So a failed call is only logged.
    """
    try:
        with client() as agent:
            agent.post(f"/api/claims/{claim_id}/resume").raise_for_status()
    except httpx.HTTPError as error:
        logger.warning("The agent's service did not pick up %s: %s", claim_id, error)


def start(path: str, body: dict[str, Any]) -> None:
    """Ask the agent's service to start a run, passing on its refusal while a run
    is going, or a 503 when it isn't running."""
    try:
        with client() as agent:
            response = agent.post(path, json=body)
    except httpx.TransportError as error:
        raise HTTPException(503, "The agent's service isn't running") from error
    if response.status_code == httpx.codes.CONFLICT:
        raise HTTPException(409, response.json()["detail"])
    response.raise_for_status()


def start_dispatch(agents: int) -> None:
    """Ask the agent's service to start a dispatch with agents claim agents at once."""
    start("/api/dispatches", {"agents": agents})


def start_evaluation(agents: int, eval_set: str, tiny: bool) -> None:
    """Ask the agent's service to start an evaluation of a labelled set."""
    start("/api/evaluations", {"agents": agents, "eval_set": eval_set, "tiny": tiny})
