import json
import sqlite3
from contextlib import closing

import pytest

from backend import agent_service
from backend.database import ROOT
from backend.tests.test_workflow import decide, pay, start

SIX = ["CLM-1001", "CLM-1002", "CLM-1003", "CLM-1004", "CLM-1005", "CLM-1006"]


def create_dispatch(client, agents=3):
    body = {"agents": agents, "model": "openai/gpt-6-luna", "reasoning_effort": "low"}
    return client.post("/api/dispatches", json=body).json()["run_id"]


def take(client, run_id, skip):
    return client.post(f"/api/runs/{run_id}/claims", json={"skip": skip})


def all_but(client, claim_ids):
    return [
        c["claim_id"]
        for c in client.get("/api/claims").json()
        if c["claim_id"] not in claim_ids
    ]


def latest(client):
    return client.get("/api/dispatches/latest").json()


def oldest_first(claim_ids):
    queue = json.loads((ROOT / "data" / "claims.json").read_text(encoding="utf-8"))
    found = [c for c in queue if c["claim_id"] in claim_ids]
    return [
        c["claim_id"]
        for c in sorted(found, key=lambda c: (c["submitted_on"], c["claim_id"]))
    ]


def test_there_is_no_dispatch_before_the_first(client):
    response = client.get("/api/dispatches/latest")
    assert response.status_code == 200
    assert response.json() is None


def test_a_new_dispatch_is_running(client):
    body = {"agents": 25, "model": "openai/gpt-6-luna", "reasoning_effort": "low"}
    run = client.post("/api/dispatches", json=body).json()
    assert run["kind"] == "dispatch"
    assert run["agents"] == 25
    assert run["model"] == "openai/gpt-6-luna"
    assert run["reasoning_effort"] == "low"
    assert run["status"] == "running"
    assert run["started_at"]
    assert run["finished_at"] is None
    found = latest(client)
    assert found["run_id"] == run["run_id"]
    assert found["claims"] == []
    assert found["cost"] == 0
    assert found["summary"] is None
    assert found["run_seconds"] is None


def test_the_latest_dispatch_is_the_newest(client):
    create_dispatch(client)
    second = create_dispatch(client, 5)
    assert latest(client)["run_id"] == second
    assert latest(client)["agents"] == 5


@pytest.mark.parametrize(
    "body",
    [
        {"agents": 0, "model": "m", "reasoning_effort": "low"},
        {"agents": 26, "model": "m", "reasoning_effort": "low"},
        {"agents": 3, "model": "m", "reasoning_effort": "high"},
        {"agents": 3, "model": "", "reasoning_effort": "none"},
        {"agents": 3, "model": "m"},
    ],
)
def test_a_dispatch_needs_valid_input(client, body):
    assert client.post("/api/dispatches", json=body).status_code == 422


def test_a_dispatch_takes_the_claims_in_progress_and_waiting_oldest_first(
    client, database
):
    with closing(sqlite3.connect(database)) as db, db:
        for claim_id, status in [
            ("CLM-1001", "decided"),
            ("CLM-1002", "waiting_for_sign_off"),
            ("CLM-1003", "left_for_handler"),
            ("CLM-1004", "in_progress"),
        ]:
            db.execute(
                "UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id)
            )
    run_id = create_dispatch(client)
    taken = take(client, run_id, ["CLM-1005"]).json()

    left_out = {"CLM-1001", "CLM-1002", "CLM-1003", "CLM-1005"}
    expected = oldest_first(set(all_but(client, left_out)))
    assert "CLM-1004" in taken
    assert taken == expected
    assert [c["claim_id"] for c in latest(client)["claims"]] == expected


def test_taking_claims_needs_a_running_run(client):
    assert take(client, 99, []).status_code == 404
    run_id = create_dispatch(client)
    client.post(f"/api/runs/{run_id}/finish")
    response = take(client, run_id, [])
    assert response.status_code == 409
    assert response.json()["detail"] == f"Run {run_id} is not running"


def test_finishing_and_stopping_runs(client):
    finished = create_dispatch(client)
    run = client.post(f"/api/runs/{finished}/finish").json()
    assert run["status"] == "finished"
    assert run["finished_at"]
    assert client.post(f"/api/runs/{finished}/finish").status_code == 409
    assert client.post("/api/runs/99/finish").status_code == 404

    running = create_dispatch(client)
    stopped = client.post("/api/runs/stop").json()
    assert [r["run_id"] for r in stopped] == [running]
    assert stopped[0]["status"] == "stopped"
    assert client.post("/api/runs/stop").json() == []
    assert latest(client)["status"] == "stopped"
    assert client.get("/api/dispatches/latest").json()["run_seconds"] is None


def record(client, claim_id, run_id, cost, seconds):
    client.post(
        f"/api/claims/{claim_id}/model-calls",
        json={"run_id": run_id, "input_tokens": 100, "output_tokens": 10, "cost": cost},
    )
    client.post(
        f"/api/claims/{claim_id}/work-times",
        json={
            "run_id": run_id,
            "started_at": "2026-11-17T10:00:00+00:00",
            "seconds": seconds,
        },
    )


def play_out(client, run_id):
    """Work six claims through the API: paid, held, declined, referred, left for a
    handler and still in progress."""
    take(client, run_id, all_but(client, SIX))
    for claim_id in SIX:
        start(client, claim_id)
    decide(client, "CLM-1001", "approve", 420)
    pay(client, "CLM-1001", 420)
    decide(client, "CLM-1002", "approve", 1350)
    decide(client, "CLM-1003", "decline", 0)
    decide(client, "CLM-1004", "refer", 0)
    for _ in range(2):
        client.post("/api/claims/CLM-1005/failure", json={"reason": "The model failed"})
        start(client, "CLM-1005")
    record(client, "CLM-1001", run_id, 0.01, 30)
    record(client, "CLM-1001", run_id, 0.02, 15)
    record(client, "CLM-1002", run_id, 0.03, 40)
    record(client, "CLM-1002", None, 0.5, 2)


def test_a_dispatch_shows_its_claims_cost_and_time(client):
    run_id = create_dispatch(client)
    play_out(client, run_id)

    found = latest(client)
    assert found["summary"] is None
    claims = {c["claim_id"]: c for c in found["claims"]}
    assert set(claims) == set(SIX)
    assert claims["CLM-1001"] == {
        "claim_id": "CLM-1001",
        "status": "decided",
        "decision": "approve",
        "payout": 420.0,
        "started_at": "2026-11-17T10:00:00+00:00",
        "seconds": 45.0,
        "cost": pytest.approx(0.03),
    }
    assert claims["CLM-1002"]["cost"] == pytest.approx(0.03)
    assert claims["CLM-1002"]["seconds"] == 40
    assert claims["CLM-1006"]["started_at"] is None
    assert claims["CLM-1006"]["seconds"] == claims["CLM-1006"]["cost"] == 0
    assert found["cost"] == pytest.approx(0.06)
    assert found["work_seconds"] == 85


def test_a_finished_dispatch_is_summed_up_from_the_records(client):
    run_id = create_dispatch(client)
    play_out(client, run_id)
    client.post(f"/api/runs/{run_id}/finish")

    found = latest(client)
    assert found["summary"] == {
        "approved": 2,
        "declined": 1,
        "referred": 1,
        "waiting_for_sign_off": [{"claim_id": "CLM-1002", "payout": 1350.0}],
        "left_for_handler": ["CLM-1005"],
        "in_progress": ["CLM-1006"],
    }
    assert found["run_seconds"] >= 0


@pytest.fixture
def asked(monkeypatch):
    """Record the dispatches the backend asks the agent's service to start."""
    started = []
    monkeypatch.setattr(agent_service, "start_dispatch", started.append)
    return started


def test_starting_a_dispatch_asks_the_agents_service(client, asked):
    response = client.post("/api/dispatches/start", json={"agents": 5})
    assert response.status_code == 202
    assert response.json() == {"status": "started"}
    assert asked == [5]
    assert latest(client) is None


@pytest.mark.parametrize("agents", [0, 26])
def test_starting_a_dispatch_needs_between_1_and_25_agents(client, asked, agents):
    response = client.post("/api/dispatches/start", json={"agents": agents})
    assert response.status_code == 422
    assert asked == []


def test_starting_a_dispatch_says_when_the_agents_service_is_not_running(
    client, monkeypatch
):
    monkeypatch.setenv("UNDERCOVER_AGENT", "http://127.0.0.1:9")
    response = client.post("/api/dispatches/start", json={"agents": 3})
    assert response.status_code == 503
    assert response.json()["detail"] == "The agent's service isn't running"
