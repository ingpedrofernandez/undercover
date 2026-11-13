import sqlite3
from contextlib import closing

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent import __main__ as cli
from agent import api, harness, work
from agent.tests.test_agent import StubModel, claim, decide, script, steps
from agent.tests.test_failures import failing, round_in_circles

NO_MODEL_CALLS: list = []


def nothing():
    return StubModel(messages=iter(NO_MODEL_CALLS))


def failures(database, claim_id):
    with closing(sqlite3.connect(database)) as db:
        query = "SELECT failures FROM claims WHERE claim_id = ?"
        return db.execute(query, (claim_id,)).fetchone()[0]


def payments(database, claim_id):
    with closing(sqlite3.connect(database)) as db:
        query = "SELECT count(*) FROM payments WHERE claim_id = ?"
        return db.execute(query, (claim_id,)).fetchone()[0]


def held(claim_id="CLM-1002"):
    return script(claim_id, "POL-2002", "CUS-3002", "approve", 1350.0)


def sign_off(client, claim_id="CLM-1002"):
    response = client.post(
        f"/api/claims/{claim_id}/sign-off", json={"handler_id": "HND-01"}
    )
    return response.json()


def test_a_held_claim_carried_on_before_a_sign_off_still_waits(client):
    work.work_claim("CLM-1002", held())
    line = work.carry_on("CLM-1002", nothing())
    assert line == "CLM-1002  approve  $1,350.00  waiting for sign-off"
    assert claim(client, "CLM-1002")["payment"] is None


def test_a_signed_off_claim_is_paid_when_carried_on(client, database):
    work.work_claim("CLM-1002", held())
    thread_id = claim(client, "CLM-1002")["thread_id"]
    signed_off = sign_off(client)["decision"]

    model = nothing()
    assert work.carry_on("CLM-1002", model) == "CLM-1002  approve  $1,350.00  paid"
    assert model.prompts == []
    found = claim(client, "CLM-1002")
    assert found["status"] == "decided"
    assert found["thread_id"] == thread_id
    assert found["payment"]["signed_off_by"] == "Dana Whitfield"
    assert found["payment"]["signed_off_at"] == signed_off["signed_off_at"]
    recorded = steps(client, "CLM-1002")
    assert recorded[-2]["content"] == 'pay_claim(claim_id="CLM-1002", amount=1350.0)'

    assert work.carry_on("CLM-1002", nothing()) == (
        "CLM-1002  approve  $1,350.00  paid"
    )
    assert payments(database, "CLM-1002") == 1
    assert steps(client, "CLM-1002") == recorded


def test_a_claim_stopped_partway_carries_on_from_its_last_step(client, database):
    first = script("CLM-1003", "POL-2003", "CUS-3003", "decline", 0)
    first.stop_at = {2}
    with pytest.raises(KeyboardInterrupt):
        work.work_claim("CLM-1003", first)
    stopped = claim(client, "CLM-1003")
    assert stopped["status"] == "in_progress"
    before = steps(client, "CLM-1003")
    assert len(before) == 4

    second = StubModel(
        messages=iter([decide("CLM-1003", "decline", 0), AIMessage("Declined.")])
    )
    assert work.carry_on("CLM-1003", second) == "CLM-1003  decline  $0.00"
    assert [type(message) for message in second.prompts[0]] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
        ToolMessage,
    ]
    found = claim(client, "CLM-1003")
    assert found["status"] == "decided"
    assert found["thread_id"] == stopped["thread_id"]
    after = steps(client, "CLM-1003")
    assert after[: len(before)] == before
    assert len(after) == len(before) + 3
    assert "error" not in {s["kind"] for s in after}
    assert failures(database, "CLM-1003") == 0


def test_a_claim_stopped_before_its_first_step_starts_on_the_same_thread(client):
    client.post("/api/claims/CLM-1003/start", json={"thread_id": "thread-1"})
    stub = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    assert work.carry_on("CLM-1003", stub) == "CLM-1003  refer  $0.00"
    assert stub.prompts[0][1] == HumanMessage(
        "Claim CLM-1003", id=stub.prompts[0][1].id
    )
    assert len(stub.prompts[0]) == 2
    assert claim(client, "CLM-1003")["thread_id"] == "thread-1"
    assert {s["thread_id"] for s in steps(client, "CLM-1003")} == {"thread-1"}


def test_a_claim_stopped_while_paying_is_paid_once(client, database, monkeypatch):
    pay = api.pay_claim

    def pay_then_stop(claim_id, amount):
        pay(claim_id, amount)
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "pay_claim", pay_then_stop)
    with pytest.raises(KeyboardInterrupt):
        work.work_claim(
            "CLM-1001", script("CLM-1001", "POL-2001", "CUS-3001", "approve", 420.0)
        )
    monkeypatch.setattr(api, "pay_claim", pay)

    model = nothing()
    assert work.carry_on("CLM-1001", model) == "CLM-1001  approve  $420.00  paid"
    assert model.prompts == []
    assert payments(database, "CLM-1001") == 1
    assert claim(client, "CLM-1001")["status"] == "decided"
    assert steps(client, "CLM-1001")[-1]["content"].startswith("pay_claim: {")


def test_a_claim_that_fails_starts_afresh_on_a_new_thread(client):
    work.work_claim("CLM-1003", failing())
    failed = claim(client, "CLM-1003")
    assert failed["status"] == "waiting"

    stub = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    assert work.work_claim("CLM-1003", stub) == "CLM-1003  refer  $0.00"
    assert claim(client, "CLM-1003")["thread_id"] != failed["thread_id"]
    assert [type(message) for message in stub.prompts[0]] == [
        SystemMessage,
        HumanMessage,
    ]


def test_the_model_call_cap_holds_across_a_stop(client):
    first = round_in_circles()
    first.stop_at = {25}
    with pytest.raises(KeyboardInterrupt):
        work.work_claim("CLM-1001", first)

    second = round_in_circles()
    line = work.carry_on("CLM-1001", second)
    assert line.startswith("CLM-1001  failed: ModelCallLimitExceeded")
    assert len(second.prompts) == harness.CLAIM_MODEL_CALLS - 25


@pytest.fixture
def stopped_run(client, database):
    """A run stopped with CLM-1002 signed off and CLM-1003 stopped partway, and
    every other claim decided."""
    client.post("/api/runs", json={"limit": 2})
    work.work_claim("CLM-1002", held())
    sign_off(client)
    stopping = script("CLM-1003", "POL-2003", "CUS-3003", "decline", 0)
    stopping.stop_at = {2}
    with pytest.raises(KeyboardInterrupt):
        work.work_claim("CLM-1003", stopping)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE claim_id NOT IN ('CLM-1002', 'CLM-1003')"
        )


def finish_decline():
    return StubModel(
        messages=iter([decide("CLM-1003", "decline", 0), AIMessage("Declined.")])
    )


def test_a_run_catches_up_before_it_starts(client, stopped_run, capsys):
    work.catch_up(finish_decline())
    assert capsys.readouterr().out.splitlines() == [
        "Run 1 was stopped before it finished",
        "CLM-1002  approve  $1,350.00  paid",
        "CLM-1003  decline  $0.00",
    ]
    run = client.get("/api/runs/latest").json()
    assert run["finished_at"]
    assert run["summary"] == work.STOPPED


def test_catching_up_with_nothing_stopped_does_nothing(client, capsys):
    work.catch_up(nothing())
    assert capsys.readouterr().out == ""


def test_the_command_line_catches_up_when_none_are_waiting(
    client, stopped_run, monkeypatch, capsys
):
    monkeypatch.setattr(harness, "model", finish_decline)
    cli.main([])
    assert capsys.readouterr().out.splitlines() == [
        "Run 1 was stopped before it finished",
        "CLM-1002  approve  $1,350.00  paid",
        "CLM-1003  decline  $0.00",
        "No claims are waiting.",
    ]


def test_claims_caught_up_do_not_count_against_the_cap(
    client, stopped_run, database, monkeypatch, capsys
):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE claims SET status = 'waiting' WHERE claim_id = 'CLM-1004'")
    runs = []
    monkeypatch.setattr(harness, "model", finish_decline)
    monkeypatch.setattr(cli, "run_queue", lambda limit: runs.append(limit) or "Done.")
    cli.main([])
    assert runs == [1]


def test_the_command_line_carries_on_a_claim_in_progress(client, monkeypatch, capsys):
    stopping = script("CLM-1003", "POL-2003", "CUS-3003", "decline", 0)
    stopping.stop_at = {2}
    with pytest.raises(KeyboardInterrupt):
        work.work_claim("CLM-1003", stopping)
    thread_id = claim(client, "CLM-1003")["thread_id"]

    monkeypatch.setattr(harness, "model", finish_decline)
    cli.main(["CLM-1003"])
    assert capsys.readouterr().out == "CLM-1003  decline  $0.00\n"
    assert claim(client, "CLM-1003")["thread_id"] == thread_id


def test_the_command_line_starts_a_waiting_claim(client, monkeypatch, capsys):
    monkeypatch.setattr(
        harness,
        "model",
        lambda: StubModel(
            messages=iter([decide("CLM-1003", "refer", 0), AIMessage("Referred.")])
        ),
    )
    cli.main(["CLM-1003"])
    assert capsys.readouterr().out == "CLM-1003  refer  $0.00\n"
    assert claim(client, "CLM-1003")["status"] == "decided"
