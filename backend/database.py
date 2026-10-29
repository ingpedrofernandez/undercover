"""The UnderCover database: its schema, and a connection for each request."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE settings (
    payout_approval_limit REAL NOT NULL
);
CREATE TABLE handlers (
    handler_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    can_approve_over_limit INTEGER NOT NULL
);
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    record TEXT NOT NULL
);
CREATE TABLE policies (
    policy_id TEXT PRIMARY KEY,
    record TEXT NOT NULL
);
CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers,
    record TEXT NOT NULL,
    status TEXT NOT NULL,
    thread_id TEXT,
    failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE decisions (
    claim_id TEXT PRIMARY KEY REFERENCES claims,
    decision TEXT NOT NULL,
    payout REAL NOT NULL,
    section TEXT NOT NULL,
    reason TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE payments (
    claim_id TEXT PRIMARY KEY REFERENCES claims,
    amount REAL NOT NULL,
    paid_at TEXT NOT NULL,
    signed_off_by TEXT
);
CREATE TABLE steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_limit INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary TEXT,
    todos TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE sections (
    document TEXT NOT NULL,
    section INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (document, section)
);
CREATE VIEW claim_view AS
SELECT
    claims.claim_id, claims.record, claims.status, claims.thread_id,
    customers.name AS customer_name,
    decisions.decision, decisions.payout, decisions.section, decisions.reason,
    decisions.decided_at,
    payments.amount, payments.paid_at, payments.signed_off_by
FROM claims
JOIN customers USING (customer_id)
LEFT JOIN decisions USING (claim_id)
LEFT JOIN payments USING (claim_id);
"""


def database_path() -> Path:
    """Return the database file from UNDERCOVER_DB, or undercover.db at the root."""
    return Path(os.getenv("UNDERCOVER_DB", str(ROOT / "undercover.db")))


def connect() -> sqlite3.Connection:
    """Open the database, with rows that can be read by column name."""
    connection = sqlite3.connect(database_path(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def database() -> Iterator[sqlite3.Connection]:
    """Open the database for one request and commit if the request succeeds."""
    with closing(connect()) as connection, connection:
        yield connection


Database = Annotated[sqlite3.Connection, Depends(database)]


def now() -> str:
    """Return the current time in UTC, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")
