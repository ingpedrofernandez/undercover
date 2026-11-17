"""The UnderCover Agent's work: dispatches over the queue, from start to finish."""

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


def stop_unfinished_runs() -> None:
    """Mark every run an earlier process left running as stopped, and say so."""
    for run in api.stop_runs():
        print(f"Run {run['run_id']} was stopped before it finished", flush=True)
