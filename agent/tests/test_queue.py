import sqlite3
import threading
import time
from contextlib import closing

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent import __main__ as cli
from agent import main
from agent.queue import QueueRun, queue_tools, run_queue
from agent.tests.test_agent import StubModel, call

THREE = ["CLM-1001", "CLM-1002", "CLM-1003"]


@pytest.fixture
def three_waiting(database):
    """Leave only CLM-1001, CLM-1002 and CLM-1003 waiting in the queue."""
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE claim_id NOT IN ('CLM-1001', 'CLM-1002', 'CLM-1003')"
        )


class ClaimAgents:
    """Stands in for the claim agent: each try on a claim declines it or fails."""

    def __init__(self, client, failures=None):
        self.client = client
        self.failures = dict(failures or {})
        self.worked: list[str] = []
        self.busy = threading.Lock()

    def __call__(self, claim_id, thread_id, llm=None):
        assert self.busy.acquire(blocking=False), "two claims worked at once"
        try:
            self.worked.append(claim_id)
            time.sleep(0.02)
            if self.failures.get(claim_id, 0) > 0:
                self.failures[claim_id] -= 1
                raise RuntimeError("The model is unavailable")
            self.client.post(
                f"/api/claims/{claim_id}/decision",
                json={
                    "decision": "decline",
                    "payout": 0,
                    "section": "Section 9, General exclusions",
                    "reason": "Excluded.",
                },
            )
            return "Declined."
        finally:
            self.busy.release()


@pytest.fixture
def claim_agents(monkeypatch, client, three_waiting):
    agents = ClaimAgents(client)
    monkeypatch.setattr(main, "run", agents)
    return agents


def work(*claim_ids):
    return [call("work_claim", claim_id=claim_id) for claim_id in claim_ids]


def queue_agent(*replies):
    return StubModel(messages=iter([*replies, AIMessage(content="The summary.")]))


def statuses(client):
    return {c["claim_id"]: c["status"] for c in client.get("/api/claims").json()}


def test_queue_tools_are_named_after_backend_operations(client):
    operations = {
        operation["operationId"]
        for path in client.get("/openapi.json").json()["paths"].values()
        for operation in path.values()
    }
    names = [t.name for t in queue_tools(QueueRun(1, 5, None))]
    assert names == ["list_claims", "write_todos", "work_claim"]
    assert set(names[:2]) <= operations


def test_the_queue_agent_gets_its_instructions_and_cap(client, claim_agents):
    stub = queue_agent(*work(*THREE))
    run_queue(3, stub)
    system, task = stub.prompts[0][:2]
    assert isinstance(system, SystemMessage)
    assert system.content == client.get("/api/instructions").json()["queue"]
    assert isinstance(task, HumanMessage)
    assert task.content == "Run 1. Work the claims queue, taking on at most 3 claims."


def todos(*statuses):
    items = ["Work CLM-1001", "Work CLM-1002", "Write the summary"]
    return [
        {"content": content, "status": status}
        for content, status in zip(items, statuses, strict=True)
    ]


def test_the_to_do_list_is_kept_on_the_run(client, claim_agents, capsys):
    stub = queue_agent(
        call("list_claims"),
        call("write_todos", todos=todos("in_progress", "to_do", "to_do")),
        *work("CLM-1001"),
        call("write_todos", todos=todos("done", "in_progress", "to_do")),
        *work("CLM-1002"),
        call("write_todos", todos=todos("done", "done", "done")),
        *work("CLM-1003"),
    )
    assert run_queue(3, stub) == "The summary."

    run = client.get("/api/runs/latest").json()
    assert run["limit"] == 3
    assert run["todos"] == todos("done", "done", "done")
    assert run["summary"] == "The summary."
    assert run["finished_at"]
    assert stub.prompts[2][-1].content == "Saved 3 items."
    assert '"claim_id":"CLM-1001"' in stub.prompts[1][-1].content
    assert capsys.readouterr().out.splitlines() == [
        "Run 1 started, capped at 3 claims",
        "CLM-1001  decline  $0.00",
        "CLM-1002  decline  $0.00",
        "CLM-1003  decline  $0.00",
    ]


def test_a_refused_to_do_list_reaches_the_agent(client, claim_agents):
    stub = queue_agent(
        call("write_todos", todos=[{"content": "", "status": "to_do"}]),
        *work(*THREE),
    )
    run_queue(3, stub)
    assert stub.prompts[1][-1].text.startswith("Refused with status 422")


def test_a_run_takes_on_no_more_claims_than_its_cap(client, claim_agents):
    stub = queue_agent(*work(*THREE))
    run_queue(2, stub)

    assert claim_agents.worked == ["CLM-1001", "CLM-1002"]
    refusal = stub.prompts[-1][-1]
    assert refusal.content == (
        "CLM-1003  not started: the run's cap of 2 claims is reached"
    )
    assert statuses(client)["CLM-1003"] == "waiting"
    assert client.get("/api/claims/CLM-1003/steps").json() == []
    assert not any(isinstance(m, HumanMessage) for m in stub.prompts[-1][2:])


def test_a_failed_claim_is_tried_again_without_counting_twice(client, claim_agents):
    claim_agents.failures = {"CLM-1001": 1}
    stub = queue_agent(*work("CLM-1001", "CLM-1002", "CLM-1003", "CLM-1001"))
    run_queue(3, stub)

    assert claim_agents.worked == ["CLM-1001", "CLM-1002", "CLM-1003", "CLM-1001"]
    assert stub.prompts[1][-1].content == (
        "CLM-1001  failed: RuntimeError: The model is unavailable. Back in the queue."
    )
    assert {statuses(client)[c] for c in THREE} == {"decided"}


def test_a_claim_that_fails_twice_does_not_stop_the_run(client, claim_agents):
    claim_agents.failures = {"CLM-1001": 2}
    stub = queue_agent(*work("CLM-1001", "CLM-1002", "CLM-1003", "CLM-1001"))
    run_queue(3, stub)

    found = statuses(client)
    assert found["CLM-1001"] == "left_for_handler"
    assert found["CLM-1002"] == found["CLM-1003"] == "decided"
    assert stub.prompts[-1][-1].content == (
        "CLM-1001  failed again: RuntimeError: The model is unavailable."
        " Left for a handler."
    )


def test_the_agent_is_sent_back_for_a_missed_claim(client, claim_agents):
    stub = StubModel(
        messages=iter(
            [
                *work("CLM-1001", "CLM-1002"),
                AIMessage(content="All done."),
                *work("CLM-1003"),
                AIMessage(content="The summary."),
            ]
        )
    )
    assert run_queue(3, stub) == "The summary."

    nudge = stub.prompts[3][-1]
    assert isinstance(nudge, HumanMessage)
    assert nudge.content == (
        "Before you finish: these claims are still waiting within this run's cap:"
        " CLM-1003. Work them, then finish with your summary."
    )
    assert {statuses(client)[c] for c in THREE} == {"decided"}


def test_claims_asked_for_together_are_worked_one_at_a_time(client, claim_agents):
    together = AIMessage(
        content="",
        tool_calls=[
            {"name": "work_claim", "args": {"claim_id": c}, "id": c} for c in THREE
        ],
    )
    run_queue(2, queue_agent(together))
    assert sorted(claim_agents.worked) in (THREE[:2], THREE[1:], THREE[::2])
    assert sum(status == "decided" for status in statuses(client).values()) == 24


def test_a_queue_agent_that_fails_still_finishes_the_run(client, claim_agents):
    stub = StubModel(messages=iter(work("CLM-1001")), fail_at={1, 2, 3})
    summary = run_queue(3, stub)

    assert summary == "The run stopped early: RuntimeError: The model is unavailable"
    run = client.get("/api/runs/latest").json()
    assert run["summary"] == summary
    assert run["finished_at"]
    assert "in_progress" not in statuses(client).values()
    assert statuses(client)["CLM-1001"] == "decided"


@pytest.fixture
def queue_runs(monkeypatch):
    runs = []
    monkeypatch.setattr(cli, "run_queue", lambda limit: runs.append(limit) or "Done.")
    return runs


def test_the_command_line_caps_a_run_at_the_waiting_claims(
    queue_runs, capsys, three_waiting
):
    cli.main([])
    cli.main(["--limit", "5"])
    assert queue_runs == [3, 5]
    assert capsys.readouterr().out == "Done.\nDone.\n"


def test_the_command_line_with_nothing_waiting(queue_runs, capsys, database):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE claims SET status = 'decided'")
    cli.main([])
    assert queue_runs == []
    assert capsys.readouterr().out == "No claims are waiting.\n"
