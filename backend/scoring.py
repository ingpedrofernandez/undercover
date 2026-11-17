"""The scores for an evaluation, as in the team's labs: how each of the agent's
answers compares with the handler's decision, and the measures for a whole run.

A claim the agent didn't decide counts as a referral with no payout.
"""

from statistics import mean
from typing import NamedTuple

from backend.models import DecisionKind, Measures, ScoredClaim

WRONGFUL_DECLINE = 1500
NEEDLESS_REFERRAL = 50


class Answer(NamedTuple):
    """A decision and its payout, the agent's or the handler's."""

    decision: DecisionKind
    payout: float


def counted(decision: DecisionKind | None, payout: float | None) -> Answer:
    """Return the agent's answer as it counts: a referral when it didn't decide."""
    return Answer("refer", 0) if decision is None else Answer(decision, payout or 0)


def is_right(answer: Answer, expected: Answer) -> bool:
    """True when the decision matches the handler's and the payout is a dollar or
    less out."""
    return (
        answer.decision == expected.decision
        and abs(answer.payout - expected.payout) <= 1
    )


def mistake_cost(answer: Answer, expected: Answer) -> float:
    """What the agent's answer costs UnderCover, against the handler's decision."""
    if answer.decision == expected.decision:
        if answer.decision == "approve":
            return abs(answer.payout - expected.payout)
        return 0
    if answer.decision == "decline":
        return WRONGFUL_DECLINE
    if answer.decision == "approve":
        return answer.payout
    return NEEDLESS_REFERRAL


def measures(claims: list[ScoredClaim], run_seconds: float | None) -> Measures:
    """The measures for a whole run: quality, cost and time."""
    answers = [counted(claim.decision, claim.payout) for claim in claims]
    return Measures(
        decision_accuracy=mean(claim.right_decision for claim in claims),
        accuracy=mean(claim.right for claim in claims),
        cost_of_mistakes=sum(claim.mistake_cost for claim in claims),
        straight_through=mean(answer.decision != "refer" for answer in answers),
        cost_per_claim=mean(claim.cost for claim in claims),
        seconds_per_claim=mean(claim.seconds for claim in claims),
        run_seconds=run_seconds,
    )
