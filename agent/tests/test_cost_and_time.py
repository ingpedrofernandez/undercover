import sqlite3
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from agent import harness, service
from agent.tests.test_agent import USAGE, StubModel, script
from agent.tests.test_failures import failing
from backend.tests.test_runs import create_dispatch


def rows(database, table, claim_id):
    with closing(sqlite3.connect(database)) as db:
        db.row_factory = sqlite3.Row
        query = f"SELECT * FROM {table} WHERE claim_id = ? ORDER BY 1"  # noqa: S608
        return [dict(row) for row in db.execute(query, (claim_id,))]


@pytest.fixture
def run_id(client):
    return create_dispatch(client)


def test_a_claim_on_its_own_records_its_cost_and_time_with_no_run(client, database):
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    harness.work_claim("CLM-1001", None, stub)

    calls = rows(database, "model_calls", "CLM-1001")
    assert len(calls) == len(stub.prompts) == 5
    for call in calls:
        assert call["run_id"] is None
        assert call["input_tokens"] == USAGE["prompt_tokens"]
        assert call["output_tokens"] == USAGE["completion_tokens"]
        assert call["cost"] == USAGE["cost"]
    [work] = rows(database, "work_times", "CLM-1001")
    assert work["run_id"] is None
    assert work["started_at"]
    assert 0 < work["seconds"] < 30


def test_a_claim_in_a_run_records_its_cost_and_time_with_the_run(
    client, database, run_id
):
    harness.work_claim(
        "CLM-1001", run_id, script("CLM-1001", "POL-2001", "CUS-3001", "refer", 0)
    )
    assert {c["run_id"] for c in rows(database, "model_calls", "CLM-1001")} == {run_id}
    assert [w["run_id"] for w in rows(database, "work_times", "CLM-1001")] == [run_id]


def test_both_tries_at_a_claim_are_recorded_with_the_run(client, database, run_id):
    first = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    first.fail_at = {2, 3, 4}
    harness.work_claim("CLM-1003", run_id, first)
    second = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    harness.work_claim("CLM-1003", run_id, second)

    calls = rows(database, "model_calls", "CLM-1003")
    assert len(calls) == 2 + 5
    assert {c["run_id"] for c in calls} == {run_id}
    assert [w["run_id"] for w in rows(database, "work_times", "CLM-1003")] == [
        run_id,
        run_id,
    ]


def test_a_wait_for_a_sign_off_is_not_counted(
    client, database, run_id, monkeypatch, capsys
):
    harness.work_claim(
        "CLM-1002",
        run_id,
        script("CLM-1002", "POL-2002", "CUS-3002", "approve", 1350.0),
    )
    calls = rows(database, "model_calls", "CLM-1002")
    time.sleep(2)
    client.post("/api/claims/CLM-1002/sign-off", json={"handler_id": "HND-01"})
    monkeypatch.setattr(harness, "model", lambda: StubModel(messages=iter([])))
    TestClient(service.app).post("/api/claims/CLM-1002/resume")

    assert capsys.readouterr().out == "CLM-1002  approve  $1,350.00  paid\n"
    held, paid = rows(database, "work_times", "CLM-1002")
    assert held["run_id"] == run_id
    assert paid["run_id"] is None
    assert held["seconds"] + paid["seconds"] < 2
    assert rows(database, "model_calls", "CLM-1002") == calls


def test_a_failed_try_records_its_time(client, database, run_id):
    harness.work_claim("CLM-1001", run_id, failing())
    assert [w["run_id"] for w in rows(database, "work_times", "CLM-1001")] == [run_id]
    assert rows(database, "model_calls", "CLM-1001") == []
