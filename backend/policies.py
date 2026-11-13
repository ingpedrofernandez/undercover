"""Finding a customer's policy, for any router that needs one."""

import json
import sqlite3

from fastapi import HTTPException

from backend.models import Policy


def find_policy(db: sqlite3.Connection, policy_id: str) -> Policy:
    """Return one policy, or raise a 404."""
    row = db.execute(
        "SELECT record FROM policies WHERE policy_id = ?", (policy_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return Policy(**json.loads(row["record"]))
