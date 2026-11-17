"""Evaluations: the agent works copies of a labelled set, and the backend scores
them against the handlers' decisions from its own records."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, RowMapping, func, insert, select

from backend import agent_service
from backend.database import (
    Database,
    claims,
    decisions,
    handler_decisions,
    held_out_claims,
    runs,
)
from backend.models import (
    CreateEvaluationRequest,
    EvalSet,
    Evaluation,
    EvaluationSummary,
    Run,
    ScoredClaim,
    StartEvaluationRequest,
)
from backend.run_records import (
    costs_in,
    create_run,
    find_run,
    run_seconds,
    times_in,
    to_run,
)
from backend.scoring import Answer, counted, is_right, measures, mistake_cost

router = APIRouter(prefix="/api/evaluations")


def sources(db: Connection, eval_set: EvalSet, tiny: bool) -> list[RowMapping]:
    """Return the claims of a labelled set, all or only its five tiny ones: the
    queue's claims for the evaluation set, the held-out claims for the other."""
    labelled = select(handler_decisions.c.claim_id).where(
        handler_decisions.c.eval_set == eval_set
    )
    if tiny:
        labelled = labelled.where(handler_decisions.c.tiny)
    table = claims if eval_set == "evaluation" else held_out_claims
    rows = db.execute(
        select(table.c.claim_id, table.c.customer_id, table.c.record)
        .where(table.c.claim_id.in_(labelled))
        .order_by(table.c.claim_id)
    )
    return list(rows.mappings())


def copy(source: RowMapping, run_id: int) -> dict[str, Any]:
    """Return a waiting copy of a claim for an evaluation, with a new id written
    into its record too."""
    claim_id = f"{source['claim_id']}-{run_id}"
    record = json.loads(source["record"]) | {"claim_id": claim_id}
    return {
        "claim_id": claim_id,
        "customer_id": source["customer_id"],
        "record": json.dumps(record),
        "status": "waiting",
        "evaluation_id": run_id,
        "source_id": source["claim_id"],
    }


def score(row: RowMapping) -> ScoredClaim:
    """Score a copy: the agent's answer against the handler's decision."""
    answer = counted(row["decision"], row["payout"])
    expected = Answer(row["handler_decision"], row["handler_payout"])
    return ScoredClaim(
        **row,
        right_decision=answer.decision == expected.decision,
        right=is_right(answer, expected),
        mistake_cost=mistake_cost(answer, expected),
    )


def scored_claims(db: Connection, row: RowMapping) -> list[ScoredClaim]:
    """Return an evaluation's copies, each scored, with its cost and time."""
    times = times_in(row["run_id"])
    costs = costs_in(row["run_id"])
    labels = (handler_decisions.c.claim_id == claims.c.source_id) & (
        handler_decisions.c.eval_set == row["eval_set"]
    )
    rows = db.execute(
        select(
            claims.c.claim_id,
            claims.c.source_id,
            claims.c.status,
            handler_decisions.c.decision.label("handler_decision"),
            handler_decisions.c.payout.label("handler_payout"),
            decisions.c.decision,
            decisions.c.payout,
            decisions.c.reason,
            func.coalesce(times.c.seconds, 0).label("seconds"),
            func.coalesce(costs.c.cost, 0).label("cost"),
        )
        .join_from(claims, handler_decisions, labels)
        .outerjoin(decisions, decisions.c.claim_id == claims.c.claim_id)
        .outerjoin(times, times.c.claim_id == claims.c.claim_id)
        .outerjoin(costs, costs.c.claim_id == claims.c.claim_id)
        .where(claims.c.evaluation_id == row["run_id"])
        .order_by(claims.c.claim_id)
    ).mappings()
    return [score(claim) for claim in rows]


def to_summary(row: RowMapping, scored: list[ScoredClaim]) -> EvaluationSummary:
    """Build an evaluation's line on the scoreboard from its row and its claims."""
    return EvaluationSummary(
        **to_run(row).model_dump(),
        claim_count=len(scored),
        measures=measures(scored, run_seconds(row)),
    )


@router.post("/start", operation_id="start_evaluation", status_code=202)
def start_evaluation(request: StartEvaluationRequest) -> dict[str, str]:
    """Ask the agent's service to start an evaluation of a labelled set."""
    agent_service.start_evaluation(request.agents, request.eval_set, request.tiny)
    return {"status": "started"}


@router.post("", operation_id="create_evaluation")
def create_evaluation(request: CreateEvaluationRequest, db: Database) -> Run:
    """Record a new evaluation of a labelled set, with a copy of each of its claims."""
    row = create_run(db, kind="evaluation", **request.model_dump())
    copies = [
        copy(s, row["run_id"]) for s in sources(db, request.eval_set, request.tiny)
    ]
    db.execute(insert(claims), copies)
    return to_run(row)


@router.get("", operation_id="list_evaluations")
def list_evaluations(db: Database) -> list[EvaluationSummary]:
    """List the evaluations, newest first, each with its measures."""
    rows = db.execute(
        select(runs).where(runs.c.kind == "evaluation").order_by(runs.c.run_id.desc())
    ).mappings()
    return [to_summary(row, scored_claims(db, row)) for row in rows]


@router.get("/{run_id}", operation_id="get_evaluation")
def get_evaluation(run_id: int, db: Database) -> Evaluation:
    """Get an evaluation with its measures and each claim scored."""
    row = find_run(db, run_id)
    if row["kind"] != "evaluation":
        raise HTTPException(404, f"Evaluation {run_id} not found")
    scored = scored_claims(db, row)
    return Evaluation(**to_summary(row, scored).model_dump(), claims=scored)
