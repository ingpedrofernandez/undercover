"""Runs of the agent over the queue, each with its to-do list."""

import json
import sqlite3

from fastapi import APIRouter, HTTPException

from backend.database import Database, now
from backend.models import FinishRequest, Run, RunRequest, TodosRequest

router = APIRouter(prefix="/api/runs")


def to_run(row: sqlite3.Row) -> Run:
    """Build a run from its row."""
    return Run(
        run_id=row["run_id"],
        limit=row["claim_limit"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        summary=row["summary"],
        todos=json.loads(row["todos"]),
    )


def find_run(db: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    """Return one run's row, or raise a 404."""
    row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return row


def open_run(db: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    """Return a run that hasn't finished, or raise a 404 or 409."""
    row = find_run(db, run_id)
    if row["finished_at"] is not None:
        raise HTTPException(409, f"Run {run_id} has finished")
    return row


@router.post("", operation_id="start_run")
def start_run(request: RunRequest, db: Database) -> Run:
    """Start a run of the agent over the queue, capped at a number of claims."""
    row = db.execute(
        "INSERT INTO runs (claim_limit, started_at) VALUES (?, ?) RETURNING *",
        (request.limit, now()),
    ).fetchone()
    return to_run(row)


@router.get("/latest", operation_id="get_latest_run")
def get_latest_run(db: Database) -> Run | None:
    """Get the most recent run with its to-do list, or null before the first run."""
    row = db.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    return None if row is None else to_run(row)


@router.put("/{run_id}/todos", operation_id="write_todos")
def write_todos(run_id: int, request: TodosRequest, db: Database) -> Run:
    """Replace the to-do list of a run that hasn't finished."""
    open_run(db, run_id)
    todos = json.dumps([todo.model_dump() for todo in request.todos])
    db.execute("UPDATE runs SET todos = ? WHERE run_id = ?", (todos, run_id))
    return to_run(find_run(db, run_id))


@router.post("/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: int, request: FinishRequest, db: Database) -> Run:
    """Finish a run with a short summary for the handlers."""
    open_run(db, run_id)
    db.execute(
        "UPDATE runs SET finished_at = ?, summary = ? WHERE run_id = ?",
        (now(), request.summary, run_id),
    )
    return to_run(find_run(db, run_id))
