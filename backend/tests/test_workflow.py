import sqlite3
from contextlib import closing

import pytest

from backend import agent_service
from backend.agent_service import resume_claim


def start(client, claim_id):
    return client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "t-1"})


def decide(client, claim_id, decision, payout):
    return client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "section": "Section 3, Trip Delay",
            "reason": "The delay was covered.",
        },
    )


def pay(client, claim_id, amount):
    return client.post(f"/api/claims/{claim_id}/payment", json={"amount": amount})


def sign_off(client, claim_id, handler_id):
    return client.post(
        f"/api/claims/{claim_id}/sign-off", json={"handler_id": handler_id}
    )


def test_start_claim(client):
    response = start(client, "CLM-1001")
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"
    assert response.json()["thread_id"] == "t-1"
    assert start(client, "CLM-1001").status_code == 409


def test_start_needs_a_thread_id(client):
    response = client.post("/api/claims/CLM-1001/start", json={"thread_id": ""})
    assert response.status_code == 422


def test_steps(client):
    assert (
        client.post(
            "/api/claims/CLM-1001/steps", json={"kind": "message", "content": "Hi"}
        ).status_code
        == 409
    )
    start(client, "CLM-1001")
    for kind, content in (("tool_call", "get_claim"), ("tool_result", "{}")):
        response = client.post(
            "/api/claims/CLM-1001/steps", json={"kind": kind, "content": content}
        )
        assert response.status_code == 200
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [(s["kind"], s["content"]) for s in steps] == [
        ("tool_call", "get_claim"),
        ("tool_result", "{}"),
    ]
    assert steps[0]["step_id"] < steps[1]["step_id"]
    assert all(s["thread_id"] == "t-1" and s["created_at"] for s in steps)
    assert client.get("/api/claims/CLM-1002/steps").json() == []
    assert client.get("/api/claims/CLM-9999/steps").status_code == 404


def test_step_kind_must_be_known(client):
    start(client, "CLM-1001")
    response = client.post(
        "/api/claims/CLM-1001/steps", json={"kind": "thought", "content": "Hmm"}
    )
    assert response.status_code == 422


def test_decision_needs_a_claim_in_progress(client):
    assert decide(client, "CLM-1001", "decline", 0).status_code == 409
    assert decide(client, "CLM-9999", "decline", 0).status_code == 404


@pytest.mark.parametrize(
    ("decision", "payout", "section"),
    [
        ("approve", 0, "Section 3"),
        ("decline", 50, "Section 3"),
        ("refer", 10, "Section 3"),
        ("maybe", 0, "Section 3"),
        ("approve", -5, "Section 3"),
        ("decline", 0, ""),
    ],
)
def test_invalid_decisions(client, decision, payout, section):
    start(client, "CLM-1001")
    response = client.post(
        "/api/claims/CLM-1001/decision",
        json={
            "decision": decision,
            "payout": payout,
            "section": section,
            "reason": "Because.",
        },
    )
    assert response.status_code == 422
    assert client.get("/api/claims/CLM-1001").json()["decision"] is None


def count(database, table, claim_id):
    with closing(sqlite3.connect(database)) as db:
        query = f"SELECT count(*) FROM {table} WHERE claim_id = ?"  # noqa: S608
        return db.execute(query, (claim_id,)).fetchone()[0]


def test_an_approval_within_the_limit_is_decided_once_paid(client, database):
    start(client, "CLM-1001")
    claim = decide(client, "CLM-1001", "approve", 420.0).json()
    assert claim["status"] == "in_progress"
    assert claim["decision"]["payout"] == 420.0
    assert claim["decision"]["signed_off_by"] is None
    assert claim["payment"] is None
    response = pay(client, "CLM-1001", 420.0)
    assert response.status_code == 200
    claim = response.json()
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 420.0
    assert claim["payment"]["signed_off_by"] is None
    assert claim["payment"]["signed_off_at"] is None
    assert client.get("/api/claims/CLM-1001").json() == claim

    again = pay(client, "CLM-1001", 420.0)
    assert again.status_code == 200
    assert again.json() == claim
    assert count(database, "payments", "CLM-1001") == 1


def test_the_same_decision_again_changes_nothing(client, database):
    start(client, "CLM-1003")
    first = decide(client, "CLM-1003", "decline", 0).json()
    again = decide(client, "CLM-1003", "decline", 0)
    assert again.status_code == 200
    assert again.json() == first
    assert count(database, "decisions", "CLM-1003") == 1


@pytest.mark.parametrize(("decision", "payout"), [("refer", 0), ("approve", 50.0)])
def test_a_different_decision_is_refused(client, decision, payout):
    start(client, "CLM-1003")
    decide(client, "CLM-1003", "decline", 0)
    response = decide(client, "CLM-1003", decision, payout)
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Claim CLM-1003 already has a different decision"
    )
    claim = client.get("/api/claims/CLM-1003").json()
    assert claim["decision"]["decision"] == "decline"


def test_an_approval_again_with_another_payout_is_refused(client):
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    assert decide(client, "CLM-1001", "approve", 420.0).status_code == 200
    assert decide(client, "CLM-1001", "approve", 400.0).status_code == 409


def test_queue_shows_the_decision(client):
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    first = client.get("/api/claims").json()[0]
    assert (first["status"], first["decision"], first["payout"]) == (
        "in_progress",
        "approve",
        420.0,
    )


def test_payment_must_match_the_payout(client):
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    response = pay(client, "CLM-1001", 500.0)
    assert response.status_code == 422
    assert (
        response.json()["detail"] == "The amount must be the approved payout of $420.00"
    )
    assert client.get("/api/claims/CLM-1001").json()["payment"] is None


def test_exactly_the_limit_needs_no_sign_off(client):
    start(client, "CLM-1002")
    claim = decide(client, "CLM-1002", "approve", 1000.0).json()
    assert claim["status"] == "in_progress"
    assert pay(client, "CLM-1002", 1000.0).json()["status"] == "decided"


def test_over_the_limit_waits_for_sign_off(client):
    start(client, "CLM-1002")
    claim = decide(client, "CLM-1002", "approve", 1350.0).json()
    assert claim["status"] == "waiting_for_sign_off"
    response = pay(client, "CLM-1002", 1350.0)
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "A payout over $1,000.00 needs a handler's sign-off"
    )
    assert client.get("/api/claims/CLM-1002").json()["payment"] is None


def test_a_sign_off_leaves_the_claim_for_the_agent_to_pay(client):
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)
    assert sign_off(client, "CLM-1002", "HND-99").status_code == 404
    response = sign_off(client, "CLM-1002", "HND-01")
    assert response.status_code == 200
    claim = response.json()
    assert claim["status"] == "in_progress"
    assert claim["decision"]["signed_off_by"] == "Dana Whitfield"
    assert claim["decision"]["signed_off_at"]
    assert claim["payment"] is None
    assert sign_off(client, "CLM-1002", "HND-01").status_code == 409

    paid = pay(client, "CLM-1002", 1350.0).json()
    assert paid["status"] == "decided"
    assert paid["payment"]["amount"] == 1350.0
    assert paid["payment"]["signed_off_by"] == "Dana Whitfield"
    assert paid["payment"]["signed_off_at"] == claim["decision"]["signed_off_at"]


def test_a_sign_off_asks_the_agent_to_resume_once_it_is_saved(
    client, database, monkeypatch, resumed
):
    def saved_sign_off(claim_id):
        with closing(sqlite3.connect(database)) as db:
            query = "SELECT signed_off_by FROM decisions WHERE claim_id = ?"
            resumed.append((claim_id, db.execute(query, (claim_id,)).fetchone()[0]))

    monkeypatch.setattr(agent_service, "resume_claim", saved_sign_off)
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)
    assert resumed == []
    sign_off(client, "CLM-1002", "HND-01")
    assert resumed == [("CLM-1002", "Dana Whitfield")]
    sign_off(client, "CLM-1002", "HND-01")
    assert len(resumed) == 1


def test_a_sign_off_stands_when_the_agent_cannot_be_reached(
    client, monkeypatch, caplog
):
    monkeypatch.setattr(agent_service, "resume_claim", resume_claim)
    monkeypatch.setenv("UNDERCOVER_AGENT", "http://127.0.0.1:9")
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)
    response = sign_off(client, "CLM-1002", "HND-01")
    assert response.status_code == 200
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "in_progress"
    assert claim["decision"]["signed_off_by"] == "Dana Whitfield"
    assert "The agent's service did not pick up CLM-1002" in caplog.text


def test_sign_off_needs_a_claim_waiting_for_it(client):
    assert sign_off(client, "CLM-1001", "HND-01").status_code == 409
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    assert sign_off(client, "CLM-1001", "HND-01").status_code == 409


def test_sign_off_needs_a_handler_who_can_approve(client, database):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE handlers SET can_approve_over_limit = 0")
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)
    response = sign_off(client, "CLM-1002", "HND-02")
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Marcus Oyelaran can't sign off payouts over $1,000.00"
    )


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_declines_and_referrals_are_decided_and_unpaid(client, decision):
    start(client, "CLM-1003")
    claim = decide(client, "CLM-1003", decision, 0).json()
    assert claim["status"] == "decided"
    assert claim["decision"]["decision"] == decision
    assert pay(client, "CLM-1003", 10.0).status_code == 409


def test_pay_needs_an_approval(client):
    start(client, "CLM-1001")
    assert pay(client, "CLM-1001", 420.0).status_code == 409


def test_list_handlers(client):
    handlers = client.get("/api/handlers").json()
    assert [h["name"] for h in handlers] == [
        "Dana Whitfield",
        "Marcus Oyelaran",
        "Priya Raman",
    ]
    assert all(h["can_approve_over_limit"] for h in handlers)


def fail(client, claim_id, reason="The model timed out."):
    return client.post(f"/api/claims/{claim_id}/failure", json={"reason": reason})


def test_failure_needs_a_claim_in_progress(client):
    assert fail(client, "CLM-1001").status_code == 409
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "decline", 0)
    assert fail(client, "CLM-1001").status_code == 409
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350)
    assert fail(client, "CLM-1002").status_code == 409
    assert fail(client, "CLM-9999").status_code == 404


def test_a_claim_with_a_decision_is_never_put_back_in_the_queue(client):
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    response = fail(client, "CLM-1001")
    assert response.status_code == 409
    assert response.json()["detail"] == "Claim CLM-1001 has a decision"
    assert client.get("/api/claims/CLM-1001").json()["status"] == "in_progress"


def test_failure_needs_a_reason(client):
    start(client, "CLM-1001")
    assert fail(client, "CLM-1001", "").status_code == 422


def test_a_first_failure_puts_the_claim_back_in_the_queue(client):
    start(client, "CLM-1001")
    response = fail(client, "CLM-1001", "The model timed out.")
    assert response.status_code == 200
    assert response.json()["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [(s["kind"], s["content"]) for s in steps] == [
        ("error", "The model timed out. Back in the queue.")
    ]
    assert steps[0]["thread_id"] == "t-1"

    retry = client.post("/api/claims/CLM-1001/start", json={"thread_id": "t-2"})
    assert retry.json()["status"] == "in_progress"
    assert retry.json()["thread_id"] == "t-2"


def test_a_second_failure_leaves_the_claim_for_a_handler(client):
    start(client, "CLM-1001")
    fail(client, "CLM-1001", "The model timed out")
    start(client, "CLM-1001")
    response = fail(client, "CLM-1001", "The model is unavailable")
    assert response.json()["status"] == "left_for_handler"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["content"] for s in steps] == [
        "The model timed out. Back in the queue.",
        "The model is unavailable. Left for a handler.",
    ]
    assert start(client, "CLM-1001").status_code == 409
    assert decide(client, "CLM-1001", "decline", 0).status_code == 409
    claims = {c["claim_id"]: c for c in client.get("/api/claims").json()}
    assert claims["CLM-1001"]["status"] == "left_for_handler"
