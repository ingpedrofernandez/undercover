"""The records claims refer to: policies, customers' earlier claims and handlers."""

import json

from fastapi import APIRouter, HTTPException

from backend.database import Database
from backend.models import Handler, Policy, PreviousClaim

router = APIRouter(prefix="/api")


@router.get("/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, db: Database) -> Policy:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    row = db.execute(
        "SELECT record FROM policies WHERE policy_id = ?", (policy_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return Policy(**json.loads(row["record"]))


@router.get("/customers/{customer_id}/claims", operation_id="get_claim_history")
def get_claim_history(customer_id: str, db: Database) -> list[PreviousClaim]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    row = db.execute(
        "SELECT record FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Customer {customer_id} not found")
    return [
        PreviousClaim(**claim) for claim in json.loads(row["record"])["previous_claims"]
    ]


@router.get("/handlers", operation_id="list_handlers")
def list_handlers(db: Database) -> list[Handler]:
    """List the claims handlers."""
    rows = db.execute("SELECT * FROM handlers ORDER BY handler_id").fetchall()
    return [Handler(**dict(row)) for row in rows]
