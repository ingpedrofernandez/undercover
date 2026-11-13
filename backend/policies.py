"""Finding a customer's policy, for any router that needs one."""

import json

from fastapi import HTTPException
from sqlalchemy import Connection, select

from backend.database import policies
from backend.models import Policy


def find_policy(db: Connection, policy_id: str) -> Policy:
    """Return one policy, or raise a 404."""
    record = db.execute(
        select(policies.c.record).where(policies.c.policy_id == policy_id)
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return Policy(**json.loads(record))
