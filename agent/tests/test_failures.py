import itertools

import pytest
from langchain_core.messages import AIMessage

from agent import __main__ as cli
from agent import api, harness, work
from agent.tests.test_agent import StubModel, call, decide, script

ALWAYS = set(range(100))


def claim(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def steps(client, claim_id):
    return client.get(f"/api/claims/{claim_id}/steps").json()


def failing():
    return StubModel(messages=iter([]), fail_at=ALWAYS)


def test_a_model_error_puts_the_claim_back_in_the_queue(client):
    line = work.work_claim("CLM-1001", failing())
    assert line == (
        "CLM-1001  failed: RuntimeError: The model is unavailable. Back in the queue."
    )
    assert claim(client, "CLM-1001")["status"] == "waiting"
    assert [(s["kind"], s["content"]) for s in steps(client, "CLM-1001")] == [
        ("error", "RuntimeError: The model is unavailable. Back in the queue.")
    ]


def test_finishing_without_a_decision_is_a_failure(client):
    stub = StubModel(messages=iter([AIMessage(content="I'm not sure.")]))
    line = work.work_claim("CLM-1001", stub)
    assert line == (
        "CLM-1001  failed: The claim agent finished without recording a decision."
        " Back in the queue."
    )
    assert claim(client, "CLM-1001")["status"] == "waiting"


def test_a_second_failure_leaves_the_claim_for_a_handler(client):
    work.work_claim("CLM-1001", failing())
    line = work.work_claim("CLM-1001", failing())
    assert line == (
        "CLM-1001  failed again: RuntimeError: The model is unavailable."
        " Left for a handler."
    )
    assert claim(client, "CLM-1001")["status"] == "left_for_handler"
    assert [s["kind"] for s in steps(client, "CLM-1001")] == ["error", "error"]
    with pytest.raises(api.ApiError, match="409: Claim CLM-1001 is not waiting"):
        work.work_claim("CLM-1001", failing())


def test_a_failed_model_call_is_retried(client):
    stub = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    stub.fail_at = {0}
    assert work.work_claim("CLM-1003", stub) == "CLM-1003  refer  $0.00"
    assert "error" not in {s["kind"] for s in steps(client, "CLM-1003")}


def test_a_claim_agent_going_round_in_circles_is_stopped(client):
    stub = StubModel(messages=itertools.repeat(call("get_claim", claim_id="CLM-1001")))
    line = work.work_claim("CLM-1001", stub)
    assert line.startswith("CLM-1001  failed: ModelCallLimitExceededError")
    assert line.endswith("Back in the queue.")
    assert len(stub.prompts) == harness.CLAIM_MODEL_CALLS
    assert claim(client, "CLM-1001")["status"] == "waiting"


def test_a_failure_after_the_decision_leaves_the_claim_decided(client):
    stub = script("CLM-1003", "POL-2003", "CUS-3003", "decline", 0)
    stub.fail_at = {4, 5, 6}
    assert work.work_claim("CLM-1003", stub) == "CLM-1003  decline  $0.00"
    assert claim(client, "CLM-1003")["status"] == "decided"
    assert "error" not in {s["kind"] for s in steps(client, "CLM-1003")}


def test_a_claim_that_is_not_waiting_is_not_started(client):
    work.work_claim("CLM-1003", script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0))
    before = steps(client, "CLM-1003")
    with pytest.raises(api.ApiError, match="409: Claim CLM-1003 is not waiting"):
        work.work_claim("CLM-1003", failing())
    assert steps(client, "CLM-1003") == before
    with pytest.raises(api.ApiError, match="404: Claim CLM-9999 not found"):
        work.work_claim("CLM-9999", failing())


def test_the_command_line_says_why_a_claim_was_not_started(capsys):
    cli.main(["CLM-9999"])
    assert capsys.readouterr().out == (
        "CLM-9999  not started: 404: Claim CLM-9999 not found\n"
    )


@pytest.mark.parametrize(
    ("payout", "pays", "line"),
    [
        (420.0, True, "CLM-1001  approve  $420.00  paid"),
        (420.0, False, "CLM-1001  approve  $420.00  not paid"),
        (1350.0, True, "CLM-1001  approve  $1,350.00  waiting for sign-off"),
    ],
)
def test_approval_lines(client, payout, pays, line):
    paying = [call("pay_claim", claim_id="CLM-1001", amount=payout)] if pays else []
    stub = StubModel(
        messages=iter(
            [
                decide("CLM-1001", "approve", payout),
                *paying,
                AIMessage(content="Done."),
            ]
        )
    )
    assert work.work_claim("CLM-1001", stub) == line
