import sqlite3
from contextlib import closing

import pytest
from langchain_core.messages import AIMessage

from agent import __main__ as cli
from agent import main
from agent.tests.test_agent import StubModel, call, decide


@pytest.fixture
def three_waiting(database):
    """Leave only CLM-1001, CLM-1002 and CLM-1003 waiting in the queue."""
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE claim_id NOT IN ('CLM-1001', 'CLM-1002', 'CLM-1003')"
        )


def deciding(claim_id, decision, payout, *extra):
    return [
        call("get_claim", claim_id=claim_id),
        decide(claim_id, decision, payout),
        *extra,
        AIMessage(content="Done."),
    ]


def test_work_queue_with_a_stub_model(monkeypatch, capsys, client, three_waiting):
    stub = StubModel(
        messages=iter(
            deciding(
                "CLM-1001",
                "approve",
                420.0,
                call("pay_claim", claim_id="CLM-1001", amount=420.0),
            )
            + deciding("CLM-1002", "approve", 1350.0)
            + deciding("CLM-1003", "refer", 0)
        )
    )
    real_run = main.run
    worked = []

    def run(claim_id, thread_id, llm=None):
        worked.append(claim_id)
        return real_run(claim_id, thread_id, stub)

    monkeypatch.setattr(main, "run", run)
    cli.main([])

    assert worked == ["CLM-1001", "CLM-1002", "CLM-1003"]
    assert capsys.readouterr().out.splitlines() == [
        "CLM-1001  approve  $420.00  paid",
        "CLM-1002  approve  $1,350.00  waiting for sign-off",
        "CLM-1003  refer  $0.00",
        "Worked 3 claims",
    ]
    claims = {c["claim_id"]: c for c in client.get("/api/claims").json()}
    assert claims["CLM-1001"]["status"] == "decided"
    assert claims["CLM-1002"]["status"] == "waiting_for_sign_off"


def test_work_queue_reports_failures_and_moves_on(
    monkeypatch, capsys, client, three_waiting
):
    def run(claim_id, thread_id, llm=None):
        if claim_id == "CLM-1001":
            raise main.BackendError("503: The model is unavailable")
        if claim_id == "CLM-1003":
            client.post(
                f"/api/claims/{claim_id}/decision",
                json={
                    "decision": "decline",
                    "payout": 0,
                    "section": "Section 9",
                    "reason": "Excluded.",
                },
            )
        return "Done."

    monkeypatch.setattr(main, "run", run)
    main.work_queue()

    assert capsys.readouterr().out.splitlines() == [
        "CLM-1001  failed: BackendError: 503: The model is unavailable."
        " Back in the queue.",
        "CLM-1002  failed: The claim agent finished without recording a decision."
        " Back in the queue.",
        "CLM-1003  decline  $0.00",
        "Worked 3 claims",
    ]
    claims = {c["claim_id"]: c for c in client.get("/api/claims").json()}
    assert claims["CLM-1001"]["status"] == "waiting"
    assert claims["CLM-1002"]["status"] == "waiting"


def test_work_queue_with_nothing_waiting(capsys, database):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE claims SET status = 'decided'")
    main.work_queue()
    assert capsys.readouterr().out == "Worked 0 claims\n"
