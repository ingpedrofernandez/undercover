import sqlite3
from contextlib import closing

from fastapi.testclient import TestClient

from agent import harness, service, work
from backend import agent_service

TINY = ["CLM-1007", "CLM-1015", "CLM-1017", "CLM-1020", "CLM-1021"]


def evaluation(client, run_id):
    return client.get(f"/api/evaluations/{run_id}").json()


def test_an_evaluation_works_copies_and_leaves_the_queue_as_it_was(
    client, agents, checkpointer, capsys
):
    queue = client.get("/api/claims").json()
    agents.choices["CLM-1020-1"] = ("approve", 1350.0)
    work.evaluate(5, "evaluation", True)

    assert client.get("/api/claims").json() == queue
    found = evaluation(client, 1)
    assert found["status"] == "finished"
    assert found["agents"] == 5
    assert found["eval_set"] == "evaluation"
    assert found["tiny"] is True
    assert found["model"] == "openai/gpt-6-luna"
    assert found["reasoning_effort"] == "low"
    claims = {claim["source_id"]: claim for claim in found["claims"]}
    assert sorted(claims) == TINY
    held = claims.pop("CLM-1020")
    assert held["status"] == "waiting_for_sign_off"
    assert (held["decision"], held["payout"]) == ("approve", 1350.0)
    assert held["mistake_cost"] == 1350 - 240
    assert {c["status"] for c in claims.values()} == {"decided"}
    assert all(c["cost"] > 0 and c["seconds"] > 0 for c in found["claims"])
    for claim in found["claims"]:
        thread_id = client.get(f"/api/claims/{claim['claim_id']}").json()["thread_id"]
        assert list(checkpointer.list({"configurable": {"thread_id": thread_id}})) == []
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Evaluation 1 started, 5 claim agents at once"
    assert out[-1] == "Evaluation 1 finished"


def test_a_dispatch_after_an_evaluation_takes_no_copy(client, database, agents, capsys):
    work.evaluate(5, "evaluation", True)
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE evaluation_id IS NULL AND claim_id != 'CLM-1003'"
        )
    work.dispatch(3, [])
    taken = client.get("/api/dispatches/latest").json()["claims"]
    assert [claim["claim_id"] for claim in taken] == ["CLM-1003"]


def test_the_service_starts_an_evaluation(client, agents, capsys):
    response = TestClient(service.app).post(
        "/api/evaluations", json={"agents": 5, "eval_set": "held_out", "tiny": True}
    )
    assert response.status_code == 202
    [found] = client.get("/api/evaluations").json()
    assert found["status"] == "finished"
    assert found["eval_set"] == "held_out"
    assert found["claim_count"] == 5


def test_a_second_start_of_an_evaluation_is_refused(client):
    agent = TestClient(service.app)
    with service.ONE_RUN_AT_A_TIME:
        response = agent.post(
            "/api/evaluations",
            json={"agents": 5, "eval_set": "evaluation", "tiny": False},
        )
    assert response.status_code == 409
    assert client.get("/api/evaluations").json() == []


def test_the_backend_asks_the_service_with_n_and_the_set(client, monkeypatch):
    asked = []
    monkeypatch.setattr(agent_service, "client", lambda: TestClient(service.app))
    monkeypatch.setattr(harness, "pool", lambda: None)
    monkeypatch.setattr(work, "evaluate", lambda *args: asked.append(args))
    body = {"agents": 5, "eval_set": "held_out", "tiny": True}
    response = client.post("/api/evaluations/start", json=body)
    assert response.status_code == 202
    assert asked == [(5, "held_out", True)]
