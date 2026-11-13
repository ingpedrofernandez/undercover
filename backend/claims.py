"""The claims queue, and the work on each claim from start to payment."""

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, RowMapping, insert, select, update

from backend.database import (
    Database,
    claims,
    customers,
    decisions,
    handlers,
    now,
    payments,
    steps,
)
from backend.models import (
    Claim,
    ClaimSummary,
    Decision,
    DecisionRequest,
    FailureRequest,
    Handler,
    Payment,
    PaymentRequest,
    SignOffRequest,
    StartRequest,
    Status,
    Step,
    StepRequest,
)
from backend.settings import approval_limit, needs_sign_off

TRIES = 2

router = APIRouter(prefix="/api/claims")

CLAIM = (
    select(
        claims.c.claim_id,
        claims.c.record,
        claims.c.status,
        claims.c.thread_id,
        customers.c.name.label("customer_name"),
        decisions.c.decision,
        decisions.c.payout,
        decisions.c.section,
        decisions.c.reason,
        decisions.c.decided_at,
        payments.c.amount,
        payments.c.paid_at,
        payments.c.signed_off_by,
    )
    .join_from(claims, customers, claims.c.customer_id == customers.c.customer_id)
    .outerjoin(decisions, decisions.c.claim_id == claims.c.claim_id)
    .outerjoin(payments, payments.c.claim_id == claims.c.claim_id)
)


def dollars(amount: float) -> str:
    """Format an amount like $1,250.00."""
    return f"${amount:,.2f}"


def find_claim(db: Connection, claim_id: str) -> RowMapping:
    """Return one claim's row, or raise a 404."""
    row = db.execute(CLAIM.where(claims.c.claim_id == claim_id)).mappings().first()
    if row is None:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return row


def to_summary(row: RowMapping) -> ClaimSummary:
    """Build a claim's line in the queue from its row."""
    return ClaimSummary(
        **json.loads(row["record"])
        | {
            "status": row["status"],
            "customer_name": row["customer_name"],
            "decision": row["decision"],
            "payout": row["payout"],
        }
    )


def to_claim(row: RowMapping) -> Claim:
    """Build a claim in full, with its decision and payment, from its row."""
    decision = None
    if row["decision"] is not None:
        decision = Decision(**{field: row[field] for field in Decision.model_fields})
    payment = None
    if row["paid_at"] is not None:
        payment = Payment(**{field: row[field] for field in Payment.model_fields})
    return Claim(
        **json.loads(row["record"])
        | {
            "status": row["status"],
            "customer_name": row["customer_name"],
            "thread_id": row["thread_id"],
            "decision": decision,
            "payment": payment,
        }
    )


def set_status(db: Connection, claim_id: str, status: Status) -> None:
    """Move a claim to a new status."""
    db.execute(
        update(claims).where(claims.c.claim_id == claim_id).values(status=status)
    )


def pay(
    db: Connection, claim_id: str, amount: float, signed_off_by: str | None
) -> Payment:
    """Record a payment on a claim."""
    payment = Payment(amount=amount, paid_at=now(), signed_off_by=signed_off_by)
    db.execute(insert(payments).values(claim_id=claim_id, **payment.model_dump()))
    return payment


def add_step(
    db: Connection, claim_id: str, thread_id: str, kind: str, content: str
) -> Step:
    """Add one step to a claim."""
    row = db.execute(
        insert(steps)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            kind=kind,
            content=content,
            created_at=now(),
        )
        .returning(*steps.c)
    )
    return Step(**row.mappings().one())


@router.get("", operation_id="list_claims")
def list_claims(db: Database) -> list[ClaimSummary]:
    """List every claim in the queue, in id order."""
    rows = db.execute(CLAIM.order_by(claims.c.claim_id)).mappings()
    return [to_summary(row) for row in rows]


@router.get("/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, db: Database) -> Claim:
    """Get one claim in full: the story, the items claimed and the documents."""
    return to_claim(find_claim(db, claim_id))


@router.post("/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, request: StartRequest, db: Database) -> Claim:
    """Start work on a waiting claim, which moves it to in progress."""
    if find_claim(db, claim_id)["status"] != "waiting":
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    db.execute(
        update(claims)
        .where(claims.c.claim_id == claim_id)
        .values(status="in_progress", thread_id=request.thread_id)
    )
    return to_claim(find_claim(db, claim_id))


@router.post("/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, request: StepRequest, db: Database) -> Step:
    """Record one step of the agent's work on a claim."""
    thread_id = find_claim(db, claim_id)["thread_id"]
    if thread_id is None:
        raise HTTPException(409, f"Claim {claim_id} has not been started")
    return add_step(db, claim_id, thread_id, request.kind, request.content)


@router.get("/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, db: Database) -> list[Step]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(db, claim_id)
    rows = db.execute(
        select(steps).where(steps.c.claim_id == claim_id).order_by(steps.c.step_id)
    ).mappings()
    return [Step(**row) for row in rows]


@router.post("/{claim_id}/failure", operation_id="record_failure")
def record_failure(claim_id: str, request: FailureRequest, db: Database) -> Claim:
    """Record a failed try on a claim; a second failure leaves it for a handler."""
    claim = find_claim(db, claim_id)
    if claim["status"] != "in_progress":
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    failures = db.execute(
        update(claims)
        .where(claims.c.claim_id == claim_id)
        .values(failures=claims.c.failures + 1)
        .returning(claims.c.failures)
    ).scalar_one()
    left = failures >= TRIES
    set_status(db, claim_id, "left_for_handler" if left else "waiting")
    note = "Left for a handler." if left else "Back in the queue."
    reason = request.reason.rstrip(".")
    add_step(db, claim_id, claim["thread_id"], "error", f"{reason}. {note}")
    return to_claim(find_claim(db, claim_id))


@router.post("/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, request: DecisionRequest, db: Database) -> Claim:
    """Record the decision on a claim; an approval over the limit waits for sign-off."""
    if find_claim(db, claim_id)["status"] != "in_progress":
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    payout = round(request.payout, 2)
    held = request.decision == "approve" and needs_sign_off(db, payout)
    db.execute(
        insert(decisions).values(
            claim_id=claim_id,
            decision=request.decision,
            payout=payout,
            section=request.section,
            reason=request.reason,
            decided_at=now(),
        )
    )
    set_status(db, claim_id, "waiting_for_sign_off" if held else "decided")
    return to_claim(find_claim(db, claim_id))


@router.post("/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, request: PaymentRequest, db: Database) -> Payment:
    """Pay an approved claim its payout, unless it needs a handler's sign-off."""
    claim = find_claim(db, claim_id)
    if claim["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} has not been approved")
    if claim["paid_at"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has already been paid")
    if claim["status"] == "waiting_for_sign_off":
        raise HTTPException(
            403,
            f"A payout over {dollars(approval_limit(db))} needs a handler's sign-off",
        )
    if round(request.amount, 2) != claim["payout"]:
        raise HTTPException(
            422, f"The amount must be the approved payout of {dollars(claim['payout'])}"
        )
    return pay(db, claim_id, claim["payout"], None)


@router.post("/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(claim_id: str, request: SignOffRequest, db: Database) -> Claim:
    """Sign off a held payout as a handler, which pays it and decides the claim."""
    claim = find_claim(db, claim_id)
    if claim["status"] != "waiting_for_sign_off":
        raise HTTPException(409, f"Claim {claim_id} is not waiting for sign-off")
    row = (
        db.execute(select(handlers).where(handlers.c.handler_id == request.handler_id))
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, f"Handler {request.handler_id} not found")
    handler = Handler(**row)
    if not handler.can_approve_over_limit:
        raise HTTPException(
            403,
            f"{handler.name} can't sign off payouts over {dollars(approval_limit(db))}",
        )
    pay(db, claim_id, claim["payout"], handler.name)
    set_status(db, claim_id, "decided")
    return to_claim(find_claim(db, claim_id))
