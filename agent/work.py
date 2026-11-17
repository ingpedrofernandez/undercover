"""The UnderCover Agent's work: a run over the queue."""

from functools import partial

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, ToolMessage
from langfuse import get_client, observe

from agent import api, harness
from agent.tools import RunContext

STOPPED = (
    "The run was stopped before it finished. The next run carried on with the"
    " claims it left in progress."
)


def catch_up(llm: BaseChatModel | None = None) -> None:
    """Finish a run that was stopped, then carry on every claim left in progress."""
    run = api.get_latest_run()
    if run is not None and run["finished_at"] is None:
        api.finish_run(run["run_id"], STOPPED)
        print(f"Run {run['run_id']} was stopped before it finished", flush=True)
    for claim in api.list_claims():
        if claim["status"] == "in_progress":
            print(harness.work_claim(claim["claim_id"], None, llm), flush=True)


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
    work_claim = partial(harness.work_claim, run_id=run_id, llm=claim_llm)
    run = RunContext(run_id, limit, work_claim)
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
