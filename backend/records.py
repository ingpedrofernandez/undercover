"""The records claims refer to: policies, customers' earlier claims and handlers."""

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from backend.database import Database, customers, handlers
from backend.models import Handler, Policy, PreviousClaim
from backend.policies import find_policy

router = APIRouter(prefix="/api")


@router.get("/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, db: Database) -> Policy:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return find_policy(db, policy_id)


@router.get("/customers/{customer_id}/claims", operation_id="get_claim_history")
def get_claim_history(customer_id: str, db: Database) -> list[PreviousClaim]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    record = db.execute(
        select(customers.c.record).where(customers.c.customer_id == customer_id)
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"Customer {customer_id} not found")
    return [PreviousClaim(**claim) for claim in json.loads(record)["previous_claims"]]


@router.get("/handlers", operation_id="list_handlers")
def list_handlers(db: Database) -> list[Handler]:
    """List the claims handlers."""
    rows = db.execute(select(handlers).order_by(handlers.c.handler_id)).mappings()
    return [Handler(**row) for row in rows]
