"""The cost and time of the agent's work on each claim, with the run it was done in."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, insert, select

from backend.database import Database, claims, model_calls, now, work_times
from backend.models import ModelCall, ModelCallRequest, WorkTime, WorkTimeRequest
from backend.run_records import find_run

router = APIRouter(prefix="/api/claims")


def check_known(db: Connection, claim_id: str, run_id: int | None) -> None:
    """Raise a 404 for an unknown claim, or an unknown run when one is given."""
    found = select(claims.c.claim_id).where(claims.c.claim_id == claim_id)
    if db.execute(found).first() is None:
        raise HTTPException(404, f"Claim {claim_id} not found")
    if run_id is not None:
        find_run(db, run_id)


@router.post("/{claim_id}/model-calls", operation_id="record_model_call")
def record_model_call(
    claim_id: str, request: ModelCallRequest, db: Database
) -> ModelCall:
    """Record the tokens and cost of one model call made on a claim."""
    check_known(db, claim_id, request.run_id)
    row = db.execute(
        insert(model_calls)
        .values(claim_id=claim_id, created_at=now(), **request.model_dump())
        .returning(*model_calls.c)
    )
    return ModelCall(**row.mappings().one())


@router.post("/{claim_id}/work-times", operation_id="record_work_time")
def record_work_time(claim_id: str, request: WorkTimeRequest, db: Database) -> WorkTime:
    """Record how long the agent worked on a claim in one piece of work."""
    check_known(db, claim_id, request.run_id)
    row = db.execute(
        insert(work_times)
        .values(claim_id=claim_id, **request.model_dump())
        .returning(*work_times.c)
    )
    return WorkTime(**row.mappings().one())
