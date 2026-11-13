"""The backend's one client for the agent's service."""

import logging
import os

import httpx

AGENT_URL = "http://127.0.0.1:8002"

logger = logging.getLogger(__name__)


def resume_claim(claim_id: str) -> None:
    """Ask the agent's service to pick a claim back up.

    A sign-off stands whether or not the service hears about it: a run of the
    agent carries on every claim in progress. So a failed call is only logged.
    """
    url = os.getenv("UNDERCOVER_AGENT", AGENT_URL)
    try:
        httpx.post(f"{url}/api/claims/{claim_id}/resume", timeout=10).raise_for_status()
    except httpx.HTTPError as error:
        logger.warning("The agent's service did not pick up %s: %s", claim_id, error)
