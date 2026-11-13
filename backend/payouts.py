"""Working out the payout on an approved claim."""

from fastapi import APIRouter

from backend.database import Database
from backend.models import Payout, PayoutRequest
from backend.payout_rules import work_out_payout
from backend.policies import find_policy
from backend.settings import needs_sign_off

router = APIRouter(prefix="/api/payouts")


@router.post("", operation_id="calculate_payout")
def calculate_payout(request: PayoutRequest, db: Database) -> Payout:
    """Work out the payout on an approved claim with UnderCover's payout rules."""
    policy = find_policy(db, request.policy_id)
    calculation, payout = work_out_payout(
        policy, request.benefit, request.lines, request.paid_by_others
    )
    return Payout(
        calculation=calculation,
        payout=payout,
        needs_sign_off=needs_sign_off(db, payout),
    )
