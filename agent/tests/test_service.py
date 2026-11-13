import sqlite3
from contextlib import closing

from fastapi.testclient import TestClient

from agent import harness, service, work
from agent.tests.test_agent import StubModel, claim, script
from backend.tests.test_openapi import follows_the_api_rules


def test_every_operation_follows_the_api_rules():
    follows_the_api_rules(TestClient(service.app).get("/openapi.json").json())


def test_health():
    response = TestClient(service.app).get("/api/health")
    assert response.json() == {"status": "ok"}


def test_a_claim_signed_off_is_paid_once_the_service_hears(
    client, database, monkeypatch, capsys
):
    work.work_claim(
        "CLM-1002", script("CLM-1002", "POL-2002", "CUS-3002", "approve", 1350.0)
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

    assert agent.post("/api/claims/CLM-1002/resume").status_code == 202
    with closing(sqlite3.connect(database)) as db:
        query = "SELECT count(*) FROM payments WHERE claim_id = 'CLM-1002'"
        assert db.execute(query).fetchone()[0] == 1
