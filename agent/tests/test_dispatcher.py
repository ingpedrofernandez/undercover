import sqlite3
import threading
import time
from contextlib import closing

import httpx
import pytest
from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import SecretStr

from agent import api, dispatcher, harness, work
from agent.harness import checkpointer as own_checkpointer
from agent.tests.test_agent import script, steps
from agent.tests.test_durable import failures

SIX = ["CLM-1001", "CLM-1002", "CLM-1003", "CLM-1004", "CLM-1005", "CLM-1006"]


def all_but(claim_ids):
    return [c["claim_id"] for c in api_claims() if c["claim_id"] not in claim_ids]


def api_claims():
    with api.client() as backend:
        return backend.get("/api/claims").json()


def claim(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def latest(client):
    return client.get("/api/dispatches/latest").json()


def statuses(client):
    return {c["claim_id"]: c["status"] for c in client.get("/api/claims").json()}


def work_times(database, claim_id):
    with closing(sqlite3.connect(database)) as db:
        query = "SELECT run_id FROM work_times WHERE claim_id = ? ORDER BY work_id"
        return [row[0] for row in db.execute(query, (claim_id,))]


def test_the_dispatcher_has_the_nodes_and_edges_of_the_design():
    graph = dispatcher.dispatcher().get_graph()
    assert set(graph.nodes) == {
        "__start__",
        "list_claims",
        "work_claim",
        "list_retries",
        "retry_claim",
        "__error_handler__work_claim",
        "__error_handler__retry_claim",
        "__end__",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", "list_claims"),
        ("list_claims", "work_claim"),
        ("work_claim", "list_retries"),
        ("list_retries", "retry_claim"),
        ("retry_claim", "__end__"),
    }


class Recorder:
    """Stands in for the claim agent: declines each claim after a short wait, and
    notes how many it works at once."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = 0
        self.most = 0
        self.order: list[str] = []

    def __call__(self, claim_id, run_id):
        with self.lock:
            self.running += 1
            self.most = max(self.most, self.running)
            self.order.append(claim_id)
        time.sleep(0.05)
        api.start_claim(claim_id, f"thread-{claim_id}")
        api.record_decision(claim_id, "decline", 0, "Section 9", "Excluded.")
        with self.lock:
            self.running -= 1
        return f"{claim_id}  decline  $0.00"


@pytest.mark.parametrize("agents_at_once", [1, 3, 6])
def test_never_more_than_n_claims_at_once(client, monkeypatch, capsys, agents_at_once):
    recorder = Recorder()
    monkeypatch.setattr(harness, "work_claim", recorder)
    ten = [c["claim_id"] for c in client.get("/api/claims").json()][:10]
    work.dispatch(agents_at_once, all_but(ten))

    assert recorder.most == agents_at_once
    taken = [c["claim_id"] for c in latest(client)["claims"]]
    assert sorted(recorder.order) == sorted(ten)
    if agents_at_once == 1:
        assert recorder.order == taken
    assert latest(client)["status"] == "finished"


def test_a_dispatch_works_every_waiting_claim(client, agents, capsys):
    work.dispatch(3, all_but(SIX))

    found = latest(client)
    assert found["status"] == "finished"
    assert found["agents"] == 3
    assert found["model"] == "openai/gpt-6-luna"
    assert found["reasoning_effort"] == "low"
    assert [c["status"] for c in found["claims"]] == ["decided"] * 6
    assert found["summary"]["declined"] == 6
    assert all(c["cost"] > 0 and c["seconds"] > 0 for c in found["claims"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"Dispatch {found['run_id']} started, 3 claim agents at once"
    assert sorted(out[1:-1]) == [f"{c}  decline  $0.00" for c in SIX]
    assert out[-1] == f"Dispatch {found['run_id']} finished"


def test_a_claim_left_in_progress_is_carried_on_as_the_same_try(
    client, database, agents, capsys
):
    stopping = script("CLM-1003", "POL-2003", "CUS-3003", "decline", 0)
    stopping.stop_at = {2}
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim("CLM-1003", None, stopping)
    before = steps(client, "CLM-1003")
    thread_id = claim(client, "CLM-1003")["thread_id"]

    work.dispatch(3, all_but(["CLM-1003", "CLM-1004"]))

    found = claim(client, "CLM-1003")
    assert found["status"] == "decided"
    assert found["thread_id"] == thread_id
    after = steps(client, "CLM-1003")
    assert after[: len(before)] == before
    assert "error" not in {s["kind"] for s in after}
    assert failures(database, "CLM-1003") == 0
    assert claim(client, "CLM-1004")["status"] == "decided"


def test_a_rate_limit_waits_and_carries_on_as_the_same_try(
    client, database, agents, capsys
):
    agents.trouble["CLM-1003"] = [ModelRateLimitError("429")] * 3
    work.dispatch(3, all_but(["CLM-1003", "CLM-1004"]))
    run_id = latest(client)["run_id"]

    found = claim(client, "CLM-1003")
    assert found["status"] == "decided"
    assert found["decision"]["decision"] == "decline"
    recorded = steps(client, "CLM-1003")
    assert {s["thread_id"] for s in recorded} == {found["thread_id"]}
    assert [s["content"] for s in recorded].count('get_claim(claim_id="CLM-1003")') == 1
    assert "error" not in {s["kind"] for s in recorded}
    assert failures(database, "CLM-1003") == 0
    assert work_times(database, "CLM-1003") == [run_id, run_id]


def test_rate_limits_that_never_stop_leave_the_claim_for_the_next_dispatch(
    client, database, agents, capsys
):
    agents.trouble["CLM-1003"] = [ModelTimeoutError("timed out")] * 100
    work.dispatch(3, all_but(["CLM-1003", "CLM-1004"]))

    assert claim(client, "CLM-1003")["status"] == "in_progress"
    assert failures(database, "CLM-1003") == 0
    assert "error" not in {s["kind"] for s in steps(client, "CLM-1003")}
    assert claim(client, "CLM-1004")["status"] == "decided"
    found = latest(client)
    assert found["status"] == "finished"
    assert found["summary"]["in_progress"] == ["CLM-1003"]
    assert (
        "CLM-1003  not finished: ModelTimeoutError: timed out. Left for the next"
        " dispatch." in capsys.readouterr().out
    )


def test_a_failed_claim_is_tried_once_more_in_the_same_dispatch(
    client, database, agents, capsys
):
    agents.trouble["CLM-1003"] = [RuntimeError("The model is unavailable")] * 3
    work.dispatch(3, all_but(["CLM-1003", "CLM-1004"]))

    found = claim(client, "CLM-1003")
    assert found["status"] == "decided"
    assert failures(database, "CLM-1003") == 1
    assert len({s["thread_id"] for s in steps(client, "CLM-1003")}) == 2
    assert latest(client)["summary"]["declined"] == 2


def test_a_claim_that_fails_twice_is_left_for_a_handler(
    client, database, agents, capsys
):
    agents.trouble["CLM-1003"] = [RuntimeError("The model is unavailable")] * 6
    work.dispatch(3, all_but(["CLM-1003", "CLM-1004"]))

    assert claim(client, "CLM-1003")["status"] == "left_for_handler"
    assert claim(client, "CLM-1004")["status"] == "decided"
    found = latest(client)
    assert found["status"] == "finished"
    assert found["summary"]["left_for_handler"] == ["CLM-1003"]


def test_a_skipped_claim_is_not_taken(client, agents, capsys):
    work.dispatch(3, all_but(["CLM-1003", "CLM-1004"]) + ["CLM-1004"])
    assert [c["claim_id"] for c in latest(client)["claims"]] == ["CLM-1003"]
    assert claim(client, "CLM-1004")["status"] == "waiting"


def test_a_held_claim_waits_and_the_next_dispatch_leaves_it(client, agents, capsys):
    agents.choices["CLM-1002"] = ("approve", 1350.0)
    work.dispatch(3, all_but(["CLM-1002", "CLM-1003"]))
    assert claim(client, "CLM-1002")["status"] == "waiting_for_sign_off"
    assert latest(client)["summary"]["waiting_for_sign_off"] == [
        {"claim_id": "CLM-1002", "payout": 1350.0}
    ]

    work.dispatch(3, all_but(["CLM-1002", "CLM-1004"]))
    assert [c["claim_id"] for c in latest(client)["claims"]] == ["CLM-1004"]


def test_an_empty_queue_is_a_dispatch_with_no_claims(client, agents, capsys):
    work.dispatch(3, all_but([]))
    found = latest(client)
    assert found["status"] == "finished"
    assert found["claims"] == []


def openrouter(answer):
    return ChatDeepSeek(
        model=harness.DEFAULT_MODEL,
        base_url=harness.OPENROUTER_BASE_URL,
        api_key=SecretStr("test-key"),
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(answer)),
    )


def test_the_model_raises_rate_limits_and_timeouts():
    def too_many(request):
        return httpx.Response(429, json={"error": {"message": "Too many requests"}})

    def too_slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(ModelRateLimitError):
        openrouter(too_many).invoke("Claim CLM-1001")
    with pytest.raises(ModelTimeoutError):
        openrouter(too_slow).invoke("Claim CLM-1001")
    assert (ModelRateLimitError, ModelTimeoutError) == harness.UNSETTLED


def test_each_claim_graph_gets_a_saver_of_its_own_on_one_pool(monkeypatch):
    shared = object()
    monkeypatch.setattr(harness, "pool", lambda: shared)
    first, second = own_checkpointer(), own_checkpointer()
    assert isinstance(first, PostgresSaver)
    assert isinstance(second, PostgresSaver)
    assert first is not second
    assert first.conn is second.conn is shared
    assert harness.CONNECTIONS == 4
    assert harness.CONNECTION_WAIT_SECONDS > 30
