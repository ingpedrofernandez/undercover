import pytest

from backend.models import ScoredClaim
from backend.scoring import Answer, counted, is_right, measures, mistake_cost

# The agent's answer, the handler's, and what the mistake costs, worked by hand.
CASES = [
    (Answer("approve", 420.4), Answer("approve", 420), 0.4),  # right, within $1
    (Answer("approve", 400), Answer("approve", 440), 40),  # right, wrong amount
    (Answer("decline", 0), Answer("approve", 300), 1500),  # wrongful decline
    (Answer("approve", 900), Answer("decline", 0), 900),  # wrongful approval
    (Answer("approve", 1350), Answer("refer", 0), 1350),  # held, still wrongful
    (Answer("refer", 0), Answer("approve", 200), 50),  # needless referral
    (Answer("decline", 0), Answer("refer", 0), 1500),  # a decline it should refer
    (Answer("decline", 0), Answer("decline", 0), 0),  # right
]


@pytest.mark.parametrize(("answer", "expected", "cost"), CASES)
def test_the_cost_of_each_kind_of_mistake(answer, expected, cost):
    assert mistake_cost(answer, expected) == pytest.approx(cost)


def test_a_right_answer_matches_the_decision_and_is_within_a_dollar():
    assert is_right(Answer("approve", 420.99), Answer("approve", 420))
    assert not is_right(Answer("approve", 421.01), Answer("approve", 420))
    assert not is_right(Answer("refer", 0), Answer("decline", 0))
    assert is_right(Answer("refer", 0), Answer("refer", 0))


def test_a_claim_with_no_decision_counts_as_a_referral():
    assert counted(None, None) == Answer("refer", 0)
    assert counted("approve", 420.0) == Answer("approve", 420.0)
    assert mistake_cost(counted(None, None), Answer("decline", 0)) == 50


def scored(answer, expected, cost, seconds):
    return ScoredClaim(
        claim_id="CLM-1001-1",
        source_id="CLM-1001",
        status="decided",
        handler_decision=expected.decision,
        handler_payout=expected.payout,
        decision=answer.decision,
        payout=answer.payout,
        reason="A reason.",
        right_decision=answer.decision == expected.decision,
        right=is_right(answer, expected),
        mistake_cost=mistake_cost(answer, expected),
        seconds=seconds,
        cost=cost,
    )


def test_the_measures_of_a_run():
    claims = [
        scored(answer, expected, cost=0.01 * n, seconds=10 * n)
        for n, (answer, expected, _) in enumerate(CASES, start=1)
    ]
    found = measures(claims, 95.0)
    assert found.decision_accuracy == pytest.approx(3 / 8)
    assert found.accuracy == pytest.approx(2 / 8)
    assert found.cost_of_mistakes == pytest.approx(
        0.4 + 40 + 1500 + 900 + 1350 + 50 + 1500
    )
    assert found.straight_through == pytest.approx(7 / 8)
    assert found.cost_per_claim == pytest.approx(0.36 / 8)
    assert found.seconds_per_claim == pytest.approx(45)
    assert found.run_seconds == 95
