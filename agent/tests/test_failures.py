import itertools

import pytest
from langchain_core.messages import AIMessage

from agent import __main__ as cli
from agent import api, harness
from agent.tests.test_agent import StubModel, call, decide, script

ALWAYS = set(range(100))


def claim(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def steps(client, claim_id):
    return client.get(f"/api/claims/{claim_id}/steps").json()


def failing():
    return StubModel(messages=iter([]), fail_at=ALWAYS)


def test_a_model_error_puts_the_claim_back_in_the_queue(client):
    stub = failing()
    line = harness.work_claim("CLM-1001", None, stub)
    assert line == (
        "CLM-1001  failed: RuntimeError: The model is unavailable. Back in the queue."
    )
    assert len(stub.prompts) == 1 + harness.RETRIES
    assert claim(client, "CLM-1001")["status"] == "waiting"
    assert [(s["kind"], s["content"]) for s in steps(client, "CLM-1001")] == [
        ("error", "RuntimeError: The model is unavailable. Back in the queue.")
    ]


def test_finishing_without_a_decision_is_a_failure(client):
    stub = StubModel(messages=iter([AIMessage(content="I'm not sure.")]))
    line = harness.work_claim("CLM-1001", None, stub)
    assert line == (
        "CLM-1001  failed: The claim agent finished without recording a decision."
        " Back in the queue."
    )
    assert claim(client, "CLM-1001")["status"] == "waiting"


def test_a_second_failure_leaves_the_claim_for_a_handler(client):
    harness.work_claim("CLM-1001", None, failing())
    line = harness.work_claim("CLM-1001", None, failing())
    assert line == (
        "CLM-1001  failed again: RuntimeError: The model is unavailable."
        " Left for a handler."
    )
    assert claim(client, "CLM-1001")["status"] == "left_for_handler"
    assert [s["kind"] for s in steps(client, "CLM-1001")] == ["error", "error"]
    with pytest.raises(api.ApiError, match="409: Claim CLM-1001 is not waiting"):
        harness.work_claim("CLM-1001", None, failing())


def test_a_failed_model_call_is_retried(client):
    stub = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    stub.fail_at = {0}
    assert harness.work_claim("CLM-1003", None, stub) == "CLM-1003  refer  $0.00"
    assert "error" not in {s["kind"] for s in steps(client, "CLM-1003")}


def round_in_circles():
    return StubModel(
        messages=(call("get_claim", claim_id="CLM-1001") for _ in itertools.count())
    )


def test_a_claim_agent_going_round_in_circles_is_stopped(client):
    stub = round_in_circles()
    line = harness.work_claim("CLM-1001", None, stub)
    assert line == (
        "CLM-1001  failed: ModelCallLimitExceeded: The claim agent made 30 model"
        " calls without finishing. Back in the queue."
    )
    assert len(stub.prompts) == harness.CLAIM_MODEL_CALLS
    assert claim(client, "CLM-1001")["status"] == "waiting"


def test_a_failure_after_the_decision_leaves_the_claim_decided(client):
    stub = script("CLM-1003", "POL-2003", "CUS-3003", "decline", 0)
    stub.fail_at = {4, 5, 6}
    assert harness.work_claim("CLM-1003", None, stub) == "CLM-1003  decline  $0.00"
    assert claim(client, "CLM-1003")["status"] == "decided"
    assert "error" not in {s["kind"] for s in steps(client, "CLM-1003")}


def test_a_claim_that_is_not_waiting_is_not_started(client):
    harness.work_claim(
        "CLM-1003", None, script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    )
    before = steps(client, "CLM-1003")
    with pytest.raises(api.ApiError, match="409: Claim CLM-1003 is not waiting"):
        harness.work_claim("CLM-1003", None, failing())
    assert steps(client, "CLM-1003") == before
    with pytest.raises(api.ApiError, match="404: Claim CLM-9999 not found"):
        harness.work_claim("CLM-9999", None, failing())


def test_the_command_line_says_why_a_claim_was_not_started(capsys):
    cli.main(["CLM-9999"])
    assert capsys.readouterr().out == (
        "CLM-9999  not started: 404: Claim CLM-9999 not found\n"
    )


def approve(payout):
    return StubModel(
        messages=iter([decide("CLM-1001", "approve", payout), AIMessage("Done.")])
    )


@pytest.mark.parametrize(
    ("payout", "line"),
    [
        (420.0, "CLM-1001  approve  $420.00  paid"),
        (1350.0, "CLM-1001  approve  $1,350.00  waiting for sign-off"),
    ],
)
def test_approval_lines(client, payout, line):
    assert harness.work_claim("CLM-1001", None, approve(payout)) == line


def test_a_claim_with_a_decision_is_reported_without_a_failure(client, monkeypatch):
    def unavailable(claim_id, amount):
        raise api.ApiError("503: The bank is unavailable")

    monkeypatch.setattr(api, "pay_claim", unavailable)
    line = harness.work_claim("CLM-1001", None, approve(420.0))
    assert line == "CLM-1001  approve  $420.00  not paid"
    assert claim(client, "CLM-1001")["status"] == "in_progress"
    assert "error" not in {s["kind"] for s in steps(client, "CLM-1001")}
