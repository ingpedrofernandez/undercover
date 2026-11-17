import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from agent import api, harness, service
from agent.tests.test_agent import StubModel, claim, script
from backend.tests.test_openapi import follows_the_api_rules
from backend.tests.test_runs import create_dispatch


def test_every_operation_follows_the_api_rules():
    follows_the_api_rules(TestClient(service.app).get("/openapi.json").json())


def test_health():
    response = TestClient(service.app).get("/api/health")
    assert response.json() == {"status": "ok"}


def test_a_claim_signed_off_is_paid_once_the_service_hears(
    client, database, monkeypatch, capsys
):
    harness.work_claim(
        "CLM-1002", None, script("CLM-1002", "POL-2002", "CUS-3002", "approve", 1350.0)
    )
    client.post("/api/claims/CLM-1002/sign-off", json={"handler_id": "HND-01"})
    capsys.readouterr()
    model = StubModel(messages=iter([]))
    monkeypatch.setattr(harness, "model", lambda: model)
    agent = TestClient(service.app)

    response = agent.post("/api/claims/CLM-1002/resume")
    assert response.status_code == 202
    found = claim(client, "CLM-1002")
    assert found["status"] == "decided"
    assert found["payment"]["signed_off_by"] == "Dana Whitfield"
    assert capsys.readouterr().out == "CLM-1002  approve  $1,350.00  paid\n"
    assert model.prompts == []

    with pytest.raises(api.ApiError, match="409: Claim CLM-1002 is not waiting"):
        agent.post("/api/claims/CLM-1002/resume")
    with closing(sqlite3.connect(database)) as db:
        query = "SELECT count(*) FROM payments WHERE claim_id = 'CLM-1002'"
        assert db.execute(query).fetchone()[0] == 1


def leave_waiting(database, claim_ids):
    with closing(sqlite3.connect(database)) as db, db:
        marks = ", ".join("?" for _ in claim_ids)
        db.execute(
            f"UPDATE claims SET status = 'decided' WHERE claim_id NOT IN ({marks})",  # noqa: S608
            claim_ids,
        )


def test_a_dispatch_starts_and_works_in_the_background(
    client, database, monkeypatch, capsys
):
    leave_waiting(database, ["CLM-1003"])
    monkeypatch.setattr(
        harness,
        "model",
        lambda: script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0),
    )
    response = TestClient(service.app).post("/api/dispatches", json={"agents": 3})

    assert response.status_code == 202
    found = client.get("/api/dispatches/latest").json()
    assert found["agents"] == 3
    assert found["status"] == "finished"
    assert [c["claim_id"] for c in found["claims"]] == ["CLM-1003"]
    assert claim(client, "CLM-1003")["status"] == "decided"
    assert "CLM-1003  refer  $0.00" in capsys.readouterr().out


def test_a_second_start_is_refused_while_a_run_is_going(client):
    agent = TestClient(service.app)
    with service.ONE_RUN_AT_A_TIME:
        response = agent.post("/api/dispatches", json={"agents": 3})
    assert response.status_code == 409
    assert response.json()["detail"] == "A dispatch or evaluation is already running"
    assert client.get("/api/dispatches/latest").json() is None


@pytest.mark.parametrize("agents", [0, 26])
def test_a_dispatch_needs_between_1_and_25_agents(agents):
    response = TestClient(service.app).post("/api/dispatches", json={"agents": agents})
    assert response.status_code == 422


def test_starting_the_service_stops_a_run_left_running(client, monkeypatch, capsys):
    run_id = create_dispatch(client)
    monkeypatch.setattr(harness, "pool", lambda: None)
    with TestClient(service.app):
        pass
    assert client.get("/api/dispatches/latest").json()["status"] == "stopped"
    assert capsys.readouterr().out == f"Run {run_id} was stopped before it finished\n"


def test_a_dispatch_skips_a_claim_being_resumed(client, database, monkeypatch):
    leave_waiting(database, ["CLM-1003"])
    monkeypatch.setattr(service, "RESUMING", {"CLM-1003"})
    TestClient(service.app).post("/api/dispatches", json={"agents": 3})
    assert client.get("/api/dispatches/latest").json()["claims"] == []
