"""UnderCover's payout rules for an approved claim.

The rules come from section 10 of the policy wording, the plan limits in data/plans.json
and sections 6, 7 and 10 of the claims manual.
"""

import json
from math import ceil, inf
from pathlib import Path

from backend.models import Benefit, CalculationStep, PayoutLine, Policy

PLANS_FILE = Path(__file__).resolve().parent.parent / "data" / "plans.json"
PLAN_DATA = json.loads(PLANS_FILE.read_text(encoding="utf-8"))
PLANS = {plan["plan"]: plan for plan in PLAN_DATA["plans"]}
ADD_ONS = {add_on["add_on"]: add_on for add_on in PLAN_DATA["add_ons"]}
DEDUCTIBLE_BENEFITS = PLAN_DATA["deductible_applies_to"]

ELECTRONICS_PLUS_LIMIT = ADD_ONS["electronics_plus"]["electronics_per_item_limit"]
CASH_LIMIT = 100.0
HOTEL_NIGHT_LIMIT = 350.0
MEALS_PER_TRAVELER_PER_DAY = 35.0

BENEFIT_MAXIMUM = {
    "trip_cancellation": "trip_cancellation_max",
    "trip_interruption": "trip_cancellation_max",
    "trip_delay": "trip_delay_max",
    "baggage_delay": "baggage_delay_max",
    "baggage": "baggage_max",
    "passport": "passport_max",
    "emergency_medical": "emergency_medical_max",
}


def step(description: str, amount: float) -> CalculationStep:
    """Make one line of the calculation, rounded to the cent."""
    return CalculationStep(step=description, amount=round(amount, 2))


def limit_for(line: PayoutLine, policy: Policy) -> float:
    """Return the most UnderCover pays for one line, or infinity for no limit."""
    plan = PLANS[policy.plan]
    travelers = len(policy.travelers)
    match line.kind:
        case "item":
            return plan["per_item_limit"] * line.quantity
        case "electronics":
            plus = "electronics_plus" in policy.add_ons
            per_item = ELECTRONICS_PLUS_LIMIT if plus else plan["per_item_limit"]
            return per_item * line.quantity
        case "hotel":
            return HOTEL_NIGHT_LIMIT * ceil(travelers / 2) * line.nights
        case "meals_without_receipts":
            return MEALS_PER_TRAVELER_PER_DAY * travelers * ceil(line.hours / 24)
        case _:
            return inf


def eligible_amount(line: PayoutLine, policy: Policy) -> CalculationStep:
    """Return the step for one line: the amount claimed, or its limit if lower."""
    limit = limit_for(line, policy)
    if line.amount > limit:
        return step(f"{line.description}, limited to ${limit:,.2f}", limit)
    return step(line.description, line.amount)


def benefit_maximum(policy: Policy, benefit: Benefit) -> float:
    """Return the plan's maximum for a benefit, at most the trip cost for a trip."""
    maximum = PLANS[policy.plan][BENEFIT_MAXIMUM[benefit]]
    if benefit in ("trip_cancellation", "trip_interruption"):
        return min(maximum, policy.trip.trip_cost)
    return maximum


def work_out_payout(
    policy: Policy, benefit: Benefit, lines: list[PayoutLine], paid_by_others: float
) -> tuple[list[CalculationStep], float]:
    """Work out the payout on an approved claim and the calculation behind it."""
    calculation = [
        eligible_amount(line, policy) for line in lines if line.kind != "cash"
    ]
    cash = sum(line.amount for line in lines if line.kind == "cash")
    if cash:
        calculation.append(
            step(f"Cash, up to ${CASH_LIMIT:,.0f} in all", min(cash, CASH_LIMIT))
        )
    total = sum(entry.amount for entry in calculation)

    if paid_by_others:
        calculation.append(
            step("Less what others have paid or refunded", -paid_by_others)
        )
        total -= paid_by_others

    deductible = PLANS[policy.plan]["deductible"]
    if benefit in DEDUCTIBLE_BENEFITS and total > 0 and deductible:
        deductible = min(deductible, total)
        calculation.append(step("Less the deductible", -deductible))
        total -= deductible

    maximum = benefit_maximum(policy, benefit)
    if total > maximum:
        calculation.append(
            step(
                f"Less the amount over the maximum of ${maximum:,.0f}", maximum - total
            )
        )
        total = maximum

    if total < 0:
        calculation.append(step("Nothing is left to pay", -total))
        total = 0.0

    return calculation, round(total, 2)
