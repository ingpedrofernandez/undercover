"""The UnderCover Agent's work: one claim at a time, or a run over the queue."""

import json
import uuid
from functools import partial
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langfuse import get_client, observe

from agent import api, harness
from agent.tools import RunContext


def steps(message: AnyMessage) -> list[tuple[str, str]]:
    """Turn one message from a claim agent's run into steps for the dashboard."""
    if isinstance(message, ToolMessage):
        if message.name == "read_section" and message.status == "success":
            return [("read", message.text)]
        return [("tool_result", f"{message.name}: {message.text}")]
    found = []
    if message.text:
        found.append(("message", message.text))
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in call["args"].items())
            found.append(("tool_call", f"{call['name']}({args})"))
    return found


def record_steps(claim_id: str, message: AnyMessage) -> None:
    """Record a message from a claim agent's run as steps on its claim."""
    for kind, content in steps(message):
        api.record_step(claim_id, kind, content)


def run_claim_agent(
    claim_id: str, thread_id: str, llm: BaseChatModel | None = None
) -> str:
    """Have a claim agent work a started claim, recording its steps."""
    return harness.run_agent(
        harness.claim_agent(llm),
        f"Claim {claim_id}",
        partial(record_steps, claim_id),
        config={"configurable": {"thread_id": thread_id}},
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


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Start a claim and work it, putting it right if it fails, and report one line."""
    thread_id = str(uuid.uuid4())
    api.start_claim(claim_id, thread_id)
    try:
        run_claim_agent(claim_id, thread_id, llm)
        problem = "The claim agent finished without recording a decision"
    except Exception as error:  # one failed claim must never stop the queue
        problem = f"{type(error).__name__}: {error}".splitlines()[0]
    claim = api.get_claim(claim_id)
    if claim["status"] != "in_progress":
        return report(claim)
    claim = api.record_failure(claim_id, problem)
    problem = problem.rstrip(".")
    if claim["status"] == "left_for_handler":
        return f"{claim_id}  failed again: {problem}. Left for a handler."
    return f"{claim_id}  failed: {problem}. Back in the queue."


@observe(name="work-claim", capture_input=False)
def work_one_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Work one claim outside a run, as a trace of its own, and report one line."""
    get_client().update_current_span(input=claim_id)
    return work_claim(claim_id, llm)


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
