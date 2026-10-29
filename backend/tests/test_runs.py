TODOS = [
    {"content": "Work CLM-1001", "status": "in_progress"},
    {"content": "Work CLM-1002", "status": "to_do"},
    {"content": "Write the summary", "status": "to_do"},
]


def start_run(client, limit=5):
    return client.post("/api/runs", json={"limit": limit})


def write(client, run_id, todos):
    return client.put(f"/api/runs/{run_id}/todos", json={"todos": todos})


def finish(client, run_id, summary="Worked 2 claims."):
    return client.post(f"/api/runs/{run_id}/finish", json={"summary": summary})


def test_there_is_no_run_before_the_first(client):
    response = client.get("/api/runs/latest")
    assert response.status_code == 200
    assert response.json() is None


def test_a_run_from_start_to_finish(client):
    run = start_run(client).json()
    assert run["run_id"] == 1
    assert run["limit"] == 5
    assert run["started_at"]
    assert run["finished_at"] is None
    assert run["summary"] is None
    assert run["todos"] == []

    assert write(client, 1, TODOS).json()["todos"] == TODOS
    assert client.get("/api/runs/latest").json()["todos"] == TODOS

    done = [todo | {"status": "done"} for todo in TODOS]
    assert write(client, 1, done).json()["todos"] == done

    finished = finish(client, 1).json()
    assert finished["finished_at"]
    assert finished["summary"] == "Worked 2 claims."
    assert client.get("/api/runs/latest").json() == finished


def test_a_finished_run_is_closed(client):
    start_run(client)
    finish(client, 1)
    assert write(client, 1, TODOS).status_code == 409
    response = finish(client, 1)
    assert response.status_code == 409
    assert response.json()["detail"] == "Run 1 has finished"


def test_the_latest_run_is_the_newest(client):
    start_run(client)
    start_run(client, 2)
    latest = client.get("/api/runs/latest").json()
    assert latest["run_id"] == 2
    assert latest["limit"] == 2


def test_unknown_runs(client):
    assert write(client, 9, TODOS).status_code == 404
    response = finish(client, 9)
    assert response.status_code == 404
    assert response.json()["detail"] == "Run 9 not found"


def test_runs_need_valid_input(client):
    assert start_run(client, 0).status_code == 422
    start_run(client)
    assert write(client, 1, [{"content": "", "status": "to_do"}]).status_code == 422
    assert write(client, 1, [{"content": "Work", "status": "maybe"}]).status_code == 422
    assert finish(client, 1, "").status_code == 422
