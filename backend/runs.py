"""Runs of the agent: dispatches over the queue, and what every run does."""

import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, RowMapping, insert, select, update

from backend import agent_service
from backend.database import Database, claims, now, run_claims, runs
from backend.models import (
    CreateDispatchRequest,
    Dispatch,
    DispatchSummary,
    HeldPayout,
    Run,
    RunClaim,
    StartDispatchRequest,
    TakeClaimsRequest,
)
from backend.run_records import claims_of, create_run, find_run, run_seconds, to_run

router = APIRouter(prefix="/api")


def open_run(db: Connection, run_id: int) -> RowMapping:
    """Return a run that is still running, or raise a 404 or 409."""
    row = find_run(db, run_id)
    if row["status"] != "running":
        raise HTTPException(409, f"Run {run_id} is not running")
    return row


def summarize(taken: list[RunClaim]) -> DispatchSummary:
    """Sum up a dispatch from the records of its claims."""
    decided = [claim.decision for claim in taken]
    return DispatchSummary(
        approved=decided.count("approve"),
        declined=decided.count("decline"),
        referred=decided.count("refer"),
        waiting_for_sign_off=[
            HeldPayout(claim_id=claim.claim_id, payout=claim.payout or 0)
            for claim in taken
            if claim.status == "waiting_for_sign_off"
        ],
        left_for_handler=[c.claim_id for c in taken if c.status == "left_for_handler"],
        in_progress=[c.claim_id for c in taken if c.status == "in_progress"],
    )


def to_dispatch(db: Connection, row: RowMapping) -> Dispatch:
    """Build a dispatch from its row, with its claims, cost, time and summary."""
    taken = claims_of(db, row["run_id"])
    return Dispatch(
        **to_run(row).model_dump(),
        cost=sum(claim.cost for claim in taken),
        run_seconds=run_seconds(row),
        work_seconds=sum(claim.seconds for claim in taken),
        claims=taken,
        summary=None if row["status"] == "running" else summarize(taken),
    )


def claims_to_work(db: Connection, run: RowMapping, skip: list[str]) -> list[str]:
    """Return a run's claims in progress and waiting, oldest submitted first: the
    queue's for a dispatch, and its own copies for an evaluation."""
    if run["kind"] == "evaluation":
        belongs = claims.c.evaluation_id == run["run_id"]
    else:
        belongs = claims.c.evaluation_id.is_(None)
    rows = db.execute(
        select(claims.c.claim_id, claims.c.record).where(
            belongs,
            claims.c.status.in_(("in_progress", "waiting")),
            claims.c.claim_id.not_in(skip),
        )
    ).mappings()
    oldest_first = sorted(
        rows,
        key=lambda row: (json.loads(row["record"])["submitted_on"], row["claim_id"]),
    )
    return [row["claim_id"] for row in oldest_first]


@router.post("/dispatches/start", operation_id="start_dispatch", status_code=202)
def start_dispatch(request: StartDispatchRequest) -> dict[str, str]:
    """Ask the agent's service to start a dispatch with N claim agents at once."""
    agent_service.start_dispatch(request.agents)
    return {"status": "started"}


@router.post("/dispatches", operation_id="create_dispatch")
def create_dispatch(request: CreateDispatchRequest, db: Database) -> Run:
    """Record a new dispatch over the queue, running with N claim agents at once."""
    return to_run(create_run(db, kind="dispatch", **request.model_dump()))


@router.get("/dispatches/latest", operation_id="get_latest_dispatch")
def get_latest_dispatch(db: Database) -> Dispatch | None:
    """Get the newest dispatch with its claims, cost, time and summary, or null."""
    row = (
        db.execute(
            select(runs)
            .where(runs.c.kind == "dispatch")
            .order_by(runs.c.run_id.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    return None if row is None else to_dispatch(db, row)


@router.post("/runs/stop", operation_id="stop_runs")
def stop_runs(db: Database) -> list[Run]:
    """Mark every run still running as stopped, as after the agent restarts."""
    rows = db.execute(
        update(runs)
        .where(runs.c.status == "running")
        .values(status="stopped")
        .returning(*runs.c)
    ).mappings()
    return [to_run(row) for row in rows]


@router.post("/runs/{run_id}/claims", operation_id="take_claims")
def take_claims(run_id: int, request: TakeClaimsRequest, db: Database) -> list[str]:
    """Pick the claims a run works, oldest submitted first, and record them on it."""
    taken = claims_to_work(db, open_run(db, run_id), request.skip)
    if taken:
        db.execute(
            insert(run_claims),
            [
                {"run_id": run_id, "claim_id": claim_id, "position": position}
                for position, claim_id in enumerate(taken)
            ],
        )
    return taken


@router.post("/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: int, db: Database) -> Run:
    """Finish a run that is still running."""
    open_run(db, run_id)
    db.execute(
        update(runs)
        .where(runs.c.run_id == run_id)
        .values(status="finished", finished_at=now())
    )
    return to_run(find_run(db, run_id))
