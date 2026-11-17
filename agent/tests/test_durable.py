import sqlite3
from contextlib import closing

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent import __main__ as cli
from agent import api, harness
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


def test_a_held_claim_is_not_worked_again_before_a_sign_off(client):
    harness.work_claim("CLM-1002", None, held())
    with pytest.raises(api.ApiError, match="409: Claim CLM-1002 is not waiting"):
        harness.work_claim("CLM-1002", None, nothing())
    found = claim(client, "CLM-1002")
    assert found["status"] == "waiting_for_sign_off"
    assert found["payment"] is None


def test_a_signed_off_claim_is_paid_when_carried_on(client, database):
    harness.work_claim("CLM-1002", None, held())
    thread_id = claim(client, "CLM-1002")["thread_id"]
    signed_off = sign_off(client)["decision"]

    model = nothing()
    assert (
        harness.work_claim("CLM-1002", None, model)
        == "CLM-1002  approve  $1,350.00  paid"
    )
    assert model.prompts == []
    found = claim(client, "CLM-1002")
    assert found["status"] == "decided"
    assert found["thread_id"] == thread_id
    assert found["payment"]["signed_off_by"] == "Dana Whitfield"
    assert found["payment"]["signed_off_at"] == signed_off["signed_off_at"]
    recorded = steps(client, "CLM-1002")
    assert recorded[-2]["content"] == 'pay_claim(claim_id="CLM-1002", amount=1350.0)'

    with pytest.raises(api.ApiError, match="409: Claim CLM-1002 is not waiting"):
        harness.work_claim("CLM-1002", None, nothing())
    assert payments(database, "CLM-1002") == 1
    assert steps(client, "CLM-1002") == recorded


def test_a_claim_stopped_partway_carries_on_from_its_last_step(client, database):
    first = script("CLM-1003", "POL-2003", "CUS-3003", "decline", 0)
    first.stop_at = {2}
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim("CLM-1003", None, first)
    stopped = claim(client, "CLM-1003")
    assert stopped["status"] == "in_progress"
    before = steps(client, "CLM-1003")
    assert len(before) == 4

    second = StubModel(
        messages=iter([decide("CLM-1003", "decline", 0), AIMessage("Declined.")])
    )
    assert harness.work_claim("CLM-1003", None, second) == "CLM-1003  decline  $0.00"
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
    assert harness.work_claim("CLM-1003", None, stub) == "CLM-1003  refer  $0.00"
    assert stub.prompts[0][1] == HumanMessage(
        "Claim CLM-1003", id=stub.prompts[0][1].id
    )
    assert len(stub.prompts[0]) == 2
    assert claim(client, "CLM-1003")["thread_id"] == "thread-1"
    assert {s["thread_id"] for s in steps(client, "CLM-1003")} == {"thread-1"}


def test_a_claim_stopped_just_after_paying_is_paid_once(client, database, monkeypatch):
    pay = api.pay_claim

    def pay_then_stop(claim_id, amount):
        pay(claim_id, amount)
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "pay_claim", pay_then_stop)
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim(
            "CLM-1001",
            None,
            script("CLM-1001", "POL-2001", "CUS-3001", "approve", 420.0),
        )
    monkeypatch.setattr(api, "pay_claim", pay)

    assert claim(client, "CLM-1001")["status"] == "decided"
    with pytest.raises(api.ApiError, match="409: Claim CLM-1001 is not waiting"):
        harness.work_claim("CLM-1001", None, nothing())
    assert payments(database, "CLM-1001") == 1


def test_a_claim_that_fails_starts_afresh_on_a_new_thread(client):
    harness.work_claim("CLM-1003", None, failing())
    failed = claim(client, "CLM-1003")
    assert failed["status"] == "waiting"

    stub = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    assert harness.work_claim("CLM-1003", None, stub) == "CLM-1003  refer  $0.00"
    assert claim(client, "CLM-1003")["thread_id"] != failed["thread_id"]
    assert [type(message) for message in stub.prompts[0]] == [
        SystemMessage,
        HumanMessage,
    ]


def test_the_model_call_cap_holds_across_a_stop(client):
    first = round_in_circles()
    first.stop_at = {25}
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim("CLM-1001", None, first)

    second = round_in_circles()
    line = harness.work_claim("CLM-1001", None, second)
    assert line.startswith("CLM-1001  failed: ModelCallLimitExceeded")
    assert len(second.prompts) == harness.CLAIM_MODEL_CALLS - 25


def finish_decline():
    return StubModel(
        messages=iter([decide("CLM-1003", "decline", 0), AIMessage("Declined.")])
    )


def test_the_command_line_carries_on_a_claim_in_progress(client, monkeypatch, capsys):
    stopping = script("CLM-1003", "POL-2003", "CUS-3003", "decline", 0)
    stopping.stop_at = {2}
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim("CLM-1003", None, stopping)
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
