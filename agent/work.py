"""The UnderCover Agent's work: dispatches over the queue and evaluations of a
labelled set, from start to finish."""

from agent import api, dispatcher, harness


def dispatch(agents: int, skip: list[str]) -> None:
    """Record a dispatch, work its claims with up to agents claim agents at once,
    leaving out skip, and finish it."""
    model, effort = harness.model_settings()
    run_id = api.create_dispatch(agents, model, effort)["run_id"]
    print(f"Dispatch {run_id} started, {agents} claim agents at once", flush=True)
    dispatcher.run(run_id, agents, skip)
    api.finish_run(run_id)
    print(f"Dispatch {run_id} finished", flush=True)


def evaluate(agents: int, eval_set: str, tiny: bool) -> None:
    """Record an evaluation, work its copies with up to agents claim agents at
    once, clear their saved progress and finish it.

    Nobody signs off a copy, so a copy held for sign-off counts as finished, and
    clearing its thread means nothing ever carries it on.
    """
    model, effort = harness.model_settings()
    run_id = api.create_evaluation(agents, eval_set, tiny, model, effort)["run_id"]
    print(f"Evaluation {run_id} started, {agents} claim agents at once", flush=True)
    for claim_id in dispatcher.run(run_id, agents, []):
        thread_id = api.get_claim(claim_id)["thread_id"]
        if thread_id is not None:
            harness.clear_progress(thread_id)
    api.finish_run(run_id)
    print(f"Evaluation {run_id} finished", flush=True)


def stop_unfinished_runs() -> None:
    """Mark every run an earlier process left running as stopped, and say so."""
    for run in api.stop_runs():
        print(f"Run {run['run_id']} was stopped before it finished", flush=True)
