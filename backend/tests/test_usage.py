import pytest

CALL = {"run_id": None, "input_tokens": 1200, "output_tokens": 80, "cost": 0.0021}
WORK = {"run_id": None, "started_at": "2026-11-17T10:00:00+00:00", "seconds": 42.5}


def start_run(client):
    return client.post("/api/runs", json={"limit": 1}).json()["run_id"]


def test_a_model_call_is_recorded_with_no_run(client):
    response = client.post("/api/claims/CLM-1001/model-calls", json=CALL)
    assert response.status_code == 200
    recorded = response.json()
    assert recorded["claim_id"] == "CLM-1001"
    assert {k: recorded[k] for k in CALL} == CALL
    assert recorded["created_at"]


def test_a_model_call_is_recorded_with_its_run(client):
    run_id = start_run(client)
    body = CALL | {"run_id": run_id}
    recorded = client.post("/api/claims/CLM-1001/model-calls", json=body).json()
    assert recorded["run_id"] == run_id


def test_a_piece_of_work_is_recorded_with_or_without_a_run(client):
    recorded = client.post("/api/claims/CLM-1001/work-times", json=WORK).json()
    assert recorded["claim_id"] == "CLM-1001"
    assert {k: recorded[k] for k in WORK} == WORK
    run_id = start_run(client)
    body = WORK | {"run_id": run_id}
    recorded = client.post("/api/claims/CLM-1001/work-times", json=body).json()
    assert recorded["run_id"] == run_id


@pytest.mark.parametrize(
    ("path", "body"), [("model-calls", CALL), ("work-times", WORK)]
)
def test_an_unknown_claim_or_run_is_not_found(client, path, body):
    response = client.post(f"/api/claims/CLM-9999/{path}", json=body)
    assert response.status_code == 404
    assert response.json()["detail"] == "Claim CLM-9999 not found"
    response = client.post(f"/api/claims/CLM-1001/{path}", json=body | {"run_id": 7})
    assert response.status_code == 404
    assert response.json()["detail"] == "Run 7 not found"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("model-calls", CALL | {"input_tokens": -1}),
        ("model-calls", CALL | {"cost": -0.01}),
        ("model-calls", {k: v for k, v in CALL.items() if k != "run_id"}),
        ("work-times", WORK | {"seconds": -1}),
        ("work-times", {k: v for k, v in WORK.items() if k != "run_id"}),
    ],
)
def test_cost_and_time_need_valid_input(client, path, body):
    assert client.post(f"/api/claims/CLM-1001/{path}", json=body).status_code == 422
