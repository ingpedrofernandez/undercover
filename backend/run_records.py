"""What the routers for runs share: creating and finding a run, and a run's claims
with their cost and time."""

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, Subquery, func, insert, select

from backend.database import (
    claims,
    decisions,
    model_calls,
    now,
    run_claims,
    runs,
    work_times,
)
from backend.models import Run, RunClaim


def create_run(db: Connection, **values: Any) -> RowMapping:
    """Record a new run, running from now."""
    row = db.execute(
        insert(runs)
        .values(status="running", started_at=now(), **values)
        .returning(*runs.c)
    )
    return row.mappings().one()


def find_run(db: Connection, run_id: int) -> RowMapping:
    """Return one run's row, or raise a 404."""
    row = db.execute(select(runs).where(runs.c.run_id == run_id)).mappings().first()
    if row is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return row


def to_run(row: RowMapping) -> Run:
    """Build a run from its row."""
    return Run(**{field: row[field] for field in Run.model_fields})


def run_seconds(row: RowMapping) -> float | None:
    """Return how long a finished run took, or None for one running or stopped."""
    if row["status"] != "finished":
        return None
    started = datetime.fromisoformat(row["started_at"])
    return (datetime.fromisoformat(row["finished_at"]) - started).total_seconds()


def times_in(run_id: int) -> Subquery:
    """Each claim's first start and time in all in a run."""
    return (
        select(
            work_times.c.claim_id,
            func.min(work_times.c.started_at).label("started_at"),
            func.sum(work_times.c.seconds).label("seconds"),
        )
        .where(work_times.c.run_id == run_id)
        .group_by(work_times.c.claim_id)
        .subquery()
    )


def costs_in(run_id: int) -> Subquery:
    """Each claim's model cost in a run."""
    return (
        select(model_calls.c.claim_id, func.sum(model_calls.c.cost).label("cost"))
        .where(model_calls.c.run_id == run_id)
        .group_by(model_calls.c.claim_id)
        .subquery()
    )


def claims_of(db: Connection, run_id: int) -> list[RunClaim]:
    """Return the claims a run took, in order, each with where it stands and its
    first start, time and cost in the run."""
    times = times_in(run_id)
    costs = costs_in(run_id)
    rows = db.execute(
        select(
            claims.c.claim_id,
            claims.c.status,
            decisions.c.decision,
            decisions.c.payout,
            times.c.started_at,
            func.coalesce(times.c.seconds, 0).label("seconds"),
            func.coalesce(costs.c.cost, 0).label("cost"),
        )
        .select_from(run_claims)
        .join(claims, claims.c.claim_id == run_claims.c.claim_id)
        .outerjoin(decisions, decisions.c.claim_id == claims.c.claim_id)
        .outerjoin(times, times.c.claim_id == claims.c.claim_id)
        .outerjoin(costs, costs.c.claim_id == claims.c.claim_id)
        .where(run_claims.c.run_id == run_id)
        .order_by(run_claims.c.position)
    ).mappings()
    return [RunClaim(**row) for row in rows]
