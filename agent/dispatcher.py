"""The dispatcher: a graph with no model that works a run's claims with up to N
claim agents at once, as in labs/week2day4.ipynb.

Each claim keeps its own thread and saves its own progress, so the dispatcher saves
none: the next dispatch finishes what a stopped one left.
"""

import operator
from typing import Annotated, Any, TypedDict, cast

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from agent import api, harness

RETRY_ATTEMPTS = 4
RETRY_WAIT_SECONDS = 10.0


class Dispatch(TypedDict):
    """What the dispatcher keeps while it works one run."""

    run_id: int
    skip: list[str]
    claims: list[str]
    retries: list[str]
    lines: Annotated[list[str], operator.add]


class ClaimTask(TypedDict):
    """One claim for a claim agent to work, in its run."""

    claim_id: str
    run_id: int


def list_claims(state: Dispatch) -> dict[str, list[str]]:
    """Take the run's claims from the backend, which records them on the run."""
    return {"claims": api.take_claims(state["run_id"], state["skip"])}


def to_claim_agents(state: Dispatch) -> list[Send]:
    """Send each claim taken to a claim agent."""
    return [
        Send("work_claim", ClaimTask(claim_id=claim_id, run_id=state["run_id"]))
        for claim_id in state["claims"]
    ]


def work_claim(state: ClaimTask) -> dict[str, list[str]]:
    """Work one claim with the claim agent, and print its line."""
    line = harness.work_claim(state["claim_id"], state["run_id"])
    print(line, flush=True)
    return {"lines": [line]}


def leave_for_next_dispatch(state: ClaimTask, error: NodeError) -> dict[str, list[str]]:
    """Leave a claim the worker couldn't finish as it is, so the dispatch goes on."""
    problem = f"{type(error.error).__name__}: {error.error}".splitlines()[0]
    line = f"{state['claim_id']}  not finished: {problem}. Left for the next dispatch."
    print(line, flush=True)
    return {"lines": [line]}


def list_retries(state: Dispatch) -> dict[str, list[str]]:
    """Find the claims that failed once in this dispatch and are back in the queue."""
    back = [c for c in state["claims"] if api.get_claim(c)["status"] == "waiting"]
    return {"retries": back}


def to_retries(state: Dispatch) -> list[Send]:
    """Send each claim back in the queue to a claim agent for one more try."""
    return [
        Send("retry_claim", ClaimTask(claim_id=claim_id, run_id=state["run_id"]))
        for claim_id in state["retries"]
    ]


def dispatcher() -> harness.Agent:
    """Build the dispatcher graph.

    A worker waits and tries again after a rate limit or a timeout, which carries
    the claim on as the same attempt. When those tries run out, or on any error
    the claim agent didn't settle, the claim is left for the next dispatch.
    """
    retry = RetryPolicy(
        retry_on=harness.UNSETTLED,
        max_attempts=RETRY_ATTEMPTS,
        initial_interval=RETRY_WAIT_SECONDS,
    )
    # LangGraph passes the handler a NodeError, which its type hints leave out.
    handler = cast(Any, leave_for_next_dispatch)
    builder = StateGraph(Dispatch)
    builder.add_node("list_claims", list_claims)
    builder.add_node(
        "work_claim", work_claim, retry_policy=retry, error_handler=handler
    )
    builder.add_node("list_retries", list_retries)
    builder.add_node(
        "retry_claim", work_claim, retry_policy=retry, error_handler=handler
    )
    builder.add_edge(START, "list_claims")
    builder.add_conditional_edges("list_claims", to_claim_agents, ["work_claim"])
    builder.add_edge("work_claim", "list_retries")
    builder.add_conditional_edges("list_retries", to_retries, ["retry_claim"])
    builder.add_edge("retry_claim", END)
    return builder.compile(name="dispatcher")


def run(run_id: int, agents: int, skip: list[str]) -> list[str]:
    """Work a run's claims with up to agents claim agents at once, leaving out
    skip, and return the claims it took."""
    start = Dispatch(run_id=run_id, skip=skip, claims=[], retries=[], lines=[])
    state = dispatcher().invoke(start, {"max_concurrency": agents})
    return state["claims"]
