"""The UnderCover Agent's work: one claim at a time, or a run over the queue."""

import uuid
from collections.abc import Callable
from functools import partial
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, ToolMessage
from langfuse import get_client, observe

from agent import api, harness
from agent.tools import RunContext

STOPPED = (
    "The run was stopped before it finished. The next run carried on with the"
    " claims it left in progress."
)


def report(claim: dict[str, Any]) -> str:
    """Describe a decided claim in one line, from the backend's record."""
    decision = claim["decision"]
    line = f"{claim['claim_id']}  {decision['decision']}  ${decision['payout']:,.2f}"
    if claim["status"] == "waiting_for_sign_off":
        return f"{line}  waiting for sign-off"
    if decision["decision"] == "approve":
        return f"{line}  {'paid' if claim['payment'] else 'not paid'}"
    return line


def outcome(claim_id: str, run: Callable[[], None]) -> str:
    """Run the claim graph, put the claim right if it fails, and report one line."""
    try:
        run()
        problem = "The claim agent finished without recording a decision"
    except Exception as error:  # one failed claim must never stop the queue
        problem = f"{type(error).__name__}: {error}".splitlines()[0]
    claim = api.get_claim(claim_id)
    if claim["decision"] is not None:
        return report(claim)
    claim = api.record_failure(claim_id, problem)
    problem = problem.rstrip(".")
    if claim["status"] == "left_for_handler":
        return f"{claim_id}  failed again: {problem}. Left for a handler."
    return f"{claim_id}  failed: {problem}. Back in the queue."


def work_thread(claim_id: str, thread_id: str, graph: harness.Agent, start: Any) -> str:
    """Run the claim graph on a claim's thread, traced in its session."""
    run = partial(harness.run_claim_graph, graph, start, thread_id)
    return harness.trace_claim(claim_id, thread_id, partial(outcome, claim_id, run))


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Start a waiting claim on a new thread and work it, and report one line."""
    graph = harness.claim_graph(llm)
    thread_id = str(uuid.uuid4())
    api.start_claim(claim_id, thread_id)
    return work_thread(claim_id, thread_id, graph, harness.claim_task(claim_id))


def carry_on(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Carry a claim in progress on from its last saved step, and report one line.

    It's the same try at the claim: its thread, steps and failures stay as they were.
    """
    graph = harness.claim_graph(llm)
    claim = api.get_claim(claim_id)
    start = harness.carry_on_input(graph, claim)
    return work_thread(claim_id, claim["thread_id"], graph, start)


def work_one_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Carry a claim in progress on, or start a waiting one, and report one line."""
    if api.get_claim(claim_id)["status"] == "in_progress":
        return carry_on(claim_id, llm)
    return work_claim(claim_id, llm)


def catch_up(llm: BaseChatModel | None = None) -> None:
    """Finish a run that was stopped, then carry on every claim left in progress."""
    run = api.get_latest_run()
    if run is not None and run["finished_at"] is None:
        api.finish_run(run["run_id"], STOPPED)
        print(f"Run {run['run_id']} was stopped before it finished", flush=True)
    for claim in api.list_claims():
        if claim["status"] == "in_progress":
            print(carry_on(claim["claim_id"], llm), flush=True)


def show_claim_report(message: AnyMessage) -> None:
    """Print each line the queue agent gets back from a claim agent."""
    if isinstance(message, ToolMessage) and message.name == "work_claim":
        print(message.text, flush=True)


@observe(name="run-queue", capture_input=False)
def run_queue(
    limit: int,
    llm: BaseChatModel | None = None,
    claim_llm: BaseChatModel | None = None,
) -> str:
    """Start a run capped at limit claims, have the queue agent work it, finish it."""
    run_id = api.start_run(limit)["run_id"]
    print(f"Run {run_id} started, capped at {limit} claims", flush=True)
    run = RunContext(run_id, limit, partial(work_claim, llm=claim_llm))
    task = f"Run {run_id}. Work the claims queue, taking on at most {limit} claims."
    get_client().update_current_span(input=task)
    try:
        summary = harness.run_agent(
            harness.queue_agent(llm), task, show_claim_report, context=run
        )
    except Exception as error:  # a run must always be finished
        summary = f"The run stopped early: {type(error).__name__}: {error}"
    summary = summary or "The run finished without a summary."
    api.finish_run(run_id, summary)
    return summary
