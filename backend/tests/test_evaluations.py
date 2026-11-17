import json
import sqlite3
from contextlib import closing

import pytest

from backend import agent_service
from backend.database import ROOT
from backend.tests.test_runs import create_dispatch, take
from backend.tests.test_workflow import decide, pay, start

TINY = ["CLM-1007", "CLM-1015", "CLM-1017", "CLM-1020", "CLM-1021"]
HELD_OUT_TINY = ["CLM-1104", "CLM-1106", "CLM-1110", "CLM-1112", "CLM-1114"]


def create_evaluation(client, eval_set="evaluation", tiny=True, agents=5):
    body = {
        "agents": agents,
        "eval_set": eval_set,
        "tiny": tiny,
        "model": "openai/gpt-6-luna",
        "reasoning_effort": "low",
    }
    return client.post("/api/evaluations", json=body).json()["run_id"]


def rows(database, query, *values):
    with closing(sqlite3.connect(database)) as db:
        return db.execute(query, values).fetchall()


def copies(database, run_id):
    query = (
        "SELECT claim_id, source_id, status, record FROM claims"
        " WHERE evaluation_id = ? ORDER BY claim_id"
    )
    return rows(database, query, run_id)


def test_seeding_keeps_the_answer_key_out_of_the_queue(client, database):
    assert rows(database, "SELECT count(*) FROM held_out_claims") == [(25,)]
    assert rows(
        database,
        "SELECT eval_set, count(*), sum(tiny) FROM handler_decisions GROUP BY eval_set",
    ) == [("evaluation", 25, 5), ("held_out", 25, 5)]
    assert len(client.get("/api/claims").json()) == 25


@pytest.mark.parametrize(
    ("eval_set", "tiny", "sources"),
    [
        ("evaluation", True, TINY),
        ("held_out", True, HELD_OUT_TINY),
    ],
)
def test_an_evaluation_works_copies_of_its_set(
    client, database, eval_set, tiny, sources
):
    queue = client.get("/api/claims").json()
    run_id = create_evaluation(client, eval_set, tiny)

    made = copies(database, run_id)
    assert [source for _, source, _, _ in made] == sources
    for claim_id, source, status, record in made:
        assert claim_id == f"{source}-{run_id}"
        assert status == "waiting"
        assert json.loads(record)["claim_id"] == claim_id
    assert client.get("/api/claims").json() == queue


def test_a_whole_set_is_copied(client, database):
    assert len(copies(database, create_evaluation(client, tiny=False))) == 25
    held_out = create_evaluation(client, "held_out", tiny=False)
    assert len(copies(database, held_out)) == 25


def test_a_new_evaluation_records_its_set_n_model_and_effort(client):
    body = {
        "agents": 25,
        "eval_set": "held_out",
        "tiny": False,
        "model": "openai/gpt-6-luna",
        "reasoning_effort": "low",
    }
    run = client.post("/api/evaluations", json=body).json()
    assert run["kind"] == "evaluation"
    assert run["status"] == "running"
    assert {k: run[k] for k in body} == body


def test_a_copy_holds_nothing_from_the_handlers_decisions(client):
    run_id = create_evaluation(client)
    copy = client.get(f"/api/claims/CLM-1015-{run_id}").json()
    original = client.get("/api/claims/CLM-1015").json()

    assert copy["claim_id"] == f"CLM-1015-{run_id}"
    assert copy["evaluation_id"] == run_id
    assert original["evaluation_id"] is None
    assert set(copy) == set(original)
    assert {
        k: v for k, v in copy.items() if k not in ("claim_id", "evaluation_id")
    } == {k: v for k, v in original.items() if k not in ("claim_id", "evaluation_id")}
    decisions = json.loads(
        (ROOT / "data" / "evals" / "decisions.json").read_text(encoding="utf-8")
    )
    [handler] = [d for d in decisions if d["claim_id"] == "CLM-1015"]
    text = json.dumps(copy)
    for field in ("reason", "reference", "tests", "decided_on"):
        assert handler[field] not in text
    assert "over_approval_limit" not in text
    assert "calculation" not in text


def test_a_copy_is_never_signed_off(client):
    run_id = create_evaluation(client)
    copy_id = f"CLM-1015-{run_id}"
    start(client, copy_id)
    decide(client, copy_id, "approve", 1350)
    response = client.post(
        f"/api/claims/{copy_id}/sign-off", json={"handler_id": "HND-01"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"Claim {copy_id} is an evaluation's copy and is never signed off"
    )
    found = client.get(f"/api/claims/{copy_id}").json()
    assert found["status"] == "waiting_for_sign_off"
    assert found["decision"]["signed_off_by"] is None


def test_an_evaluation_takes_its_copies_and_a_dispatch_none(client):
    run_id = create_evaluation(client)
    taken = take(client, run_id, []).json()
    copied = [f"{source}-{run_id}" for source in TINY]
    assert sorted(taken) == sorted(copied)
    submitted = {
        c: client.get(f"/api/claims/{c}").json()["submitted_on"] for c in taken
    }
    assert taken == sorted(taken, key=lambda c: (submitted[c], c))

    dispatch = create_dispatch(client)
    assert not set(take(client, dispatch, []).json()) & set(copied)


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
    """Answer the five tiny claims of the evaluation set through the API.

    The handlers: CLM-1007 approve $50, CLM-1015 decline, CLM-1017 refer,
    CLM-1020 approve $240 and CLM-1021 approve $825.
    """
    take(client, run_id, [])
    answers = {
        "CLM-1007": ("approve", 50.4),  # right, within a dollar: $0.40
        "CLM-1015": ("approve", 1350),  # wrongful approval, held: $1,350
        "CLM-1017": ("refer", 0),  # right: $0
        "CLM-1020": ("approve", 200),  # right decision, $40 out: $40
    }
    for n, source in enumerate(TINY, start=1):
        claim_id = f"{source}-{run_id}"
        start(client, claim_id)
        if source in answers:
            decide(client, claim_id, *answers[source])
            record(client, claim_id, run_id, 0.01 * n, 10 * n)
    for source in ("CLM-1007", "CLM-1020"):
        pay(client, f"{source}-{run_id}", answers[source][1])
    # CLM-1021 is left undecided, so it counts as a needless referral: $50.


def test_an_evaluation_is_scored_from_the_records(client):
    run_id = create_evaluation(client)
    play_out(client, run_id)
    client.post(f"/api/runs/{run_id}/finish")

    found = client.get(f"/api/evaluations/{run_id}").json()
    measures = found["measures"]
    assert measures["decision_accuracy"] == pytest.approx(3 / 5)
    assert measures["accuracy"] == pytest.approx(2 / 5)
    assert measures["cost_of_mistakes"] == pytest.approx(0.4 + 1350 + 0 + 40 + 50)
    assert measures["straight_through"] == pytest.approx(3 / 5)
    assert measures["cost_per_claim"] == pytest.approx(0.10 / 5)
    assert measures["seconds_per_claim"] == pytest.approx(100 / 5)
    assert measures["run_seconds"] >= 0
    assert found["claim_count"] == 5
    assert found["eval_set"] == "evaluation"
    assert found["tiny"] is True

    claims = {c["source_id"]: c for c in found["claims"]}
    assert claims["CLM-1007"] | {"reason": None} == {
        "claim_id": f"CLM-1007-{run_id}",
        "source_id": "CLM-1007",
        "status": "decided",
        "handler_decision": "approve",
        "handler_payout": 50.0,
        "decision": "approve",
        "payout": 50.4,
        "reason": None,
        "right_decision": True,
        "right": True,
        "mistake_cost": pytest.approx(0.4),
        "seconds": 10.0,
        "cost": pytest.approx(0.01),
    }
    assert claims["CLM-1007"]["reason"] == "The delay was covered."
    assert claims["CLM-1015"]["status"] == "waiting_for_sign_off"
    assert claims["CLM-1015"]["mistake_cost"] == 1350
    assert claims["CLM-1021"]["decision"] is None
    assert claims["CLM-1021"]["mistake_cost"] == 50
    assert claims["CLM-1021"]["right_decision"] is False

    [listed] = client.get("/api/evaluations").json()
    assert listed["measures"] == measures
    assert "claims" not in listed


def test_evaluations_are_listed_newest_first_and_a_stopped_one_shows(client):
    first = create_evaluation(client)
    client.post(f"/api/runs/{first}/finish")
    second = create_evaluation(client, "held_out")
    client.post("/api/runs/stop")

    listed = client.get("/api/evaluations").json()
    assert [e["run_id"] for e in listed] == [second, first]
    assert listed[0]["status"] == "stopped"
    assert listed[0]["measures"]["run_seconds"] is None
    assert listed[1]["status"] == "finished"
    assert listed[0]["measures"]["straight_through"] == 0


def test_an_unknown_evaluation_is_not_found(client):
    assert client.get("/api/evaluations/99").status_code == 404
    dispatch = create_dispatch(client)
    response = client.get(f"/api/evaluations/{dispatch}")
    assert response.status_code == 404
    assert response.json()["detail"] == f"Evaluation {dispatch} not found"


@pytest.fixture
def asked(monkeypatch):
    """Record the evaluations the backend asks the agent's service to start."""
    started = []
    monkeypatch.setattr(
        agent_service,
        "start_evaluation",
        lambda agents, eval_set, tiny: started.append((agents, eval_set, tiny)),
    )
    return started


def test_starting_an_evaluation_asks_the_agents_service(client, asked):
    body = {"agents": 5, "eval_set": "held_out", "tiny": True}
    response = client.post("/api/evaluations/start", json=body)
    assert response.status_code == 202
    assert asked == [(5, "held_out", True)]
    assert client.get("/api/evaluations").json() == []


@pytest.mark.parametrize(
    "body",
    [
        {"agents": 5, "eval_set": "harder", "tiny": True},
        {"agents": 26, "eval_set": "held_out", "tiny": True},
        {"agents": 5, "eval_set": "held_out"},
    ],
)
def test_starting_an_evaluation_needs_valid_input(client, asked, body):
    assert client.post("/api/evaluations/start", json=body).status_code == 422
    assert asked == []


def test_starting_an_evaluation_says_when_the_agents_service_is_not_running(
    client, monkeypatch
):
    monkeypatch.setenv("UNDERCOVER_AGENT", "http://127.0.0.1:9")
    body = {"agents": 5, "eval_set": "evaluation", "tiny": False}
    response = client.post("/api/evaluations/start", json=body)
    assert response.status_code == 503
    assert response.json()["detail"] == "The agent's service isn't running"
