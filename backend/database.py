"""The UnderCover database: its tables, the engine, and a connection for each request.

The records live in Supabase when DATABASE_URL is set, in the undercover schema,
and otherwise in SQLite. The same queries work on both.
"""

import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Annotated

from anyio import Semaphore
from fastapi import Depends
from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    Engine,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
    make_url,
)
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "undercover"
CONNECTIONS = 4
CONNECTION_SLOTS = Semaphore(CONNECTIONS)

metadata = MetaData()

settings = Table(
    "settings", metadata, Column("payout_approval_limit", Float, nullable=False)
)
handlers = Table(
    "handlers",
    metadata,
    Column("handler_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("can_approve_over_limit", Boolean, nullable=False),
)
customers = Table(
    "customers",
    metadata,
    Column("customer_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("record", Text, nullable=False),
)
policies = Table(
    "policies",
    metadata,
    Column("policy_id", Text, primary_key=True),
    Column("record", Text, nullable=False),
)
claims = Table(
    "claims",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("customer_id", Text, ForeignKey("customers.customer_id"), nullable=False),
    Column("record", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("thread_id", Text),
    Column("failures", Integer, nullable=False, server_default="0"),
)
decisions = Table(
    "decisions",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Float, nullable=False),
    Column("section", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
)
payments = Table(
    "payments",
    metadata,
    Column("claim_id", Text, ForeignKey("claims.claim_id"), primary_key=True),
    Column("amount", Float, nullable=False),
    Column("paid_at", Text, nullable=False),
    Column("signed_off_by", Text),
)
steps = Table(
    "steps",
    metadata,
    Column("step_id", Integer, primary_key=True),
    Column("claim_id", Text, ForeignKey("claims.claim_id"), nullable=False),
    Column("thread_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)
runs = Table(
    "runs",
    metadata,
    Column("run_id", Integer, primary_key=True),
    Column("claim_limit", Integer, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("finished_at", Text),
    Column("summary", Text),
    Column("todos", Text, nullable=False, server_default="[]"),
)
sections = Table(
    "sections",
    metadata,
    Column("document", Text, primary_key=True),
    Column("section", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("text", Text, nullable=False),
)


def database_url() -> str:
    """Return DATABASE_URL, or SQLite at UNDERCOVER_DB or undercover.db at the root."""
    if url := os.getenv("DATABASE_URL"):
        return url
    return f"sqlite:///{os.getenv('UNDERCOVER_DB', ROOT / 'undercover.db')}"


def engine() -> Engine:
    """Return the engine for the database this process uses."""
    return engine_for(database_url())


@cache
def engine_for(url: str) -> Engine:
    """Build one engine per database: Supabase with a pool of four, or SQLite.

    SQLite opens the file for each request and closes it after, so the file can
    be replaced while the backend runs.
    """
    parsed = make_url(url)
    if parsed.drivername == "sqlite":
        return create_engine(parsed, poolclass=NullPool)
    return create_engine(
        parsed.set(drivername="postgresql+psycopg"),
        pool_size=CONNECTIONS,
        max_overflow=0,
        connect_args={"options": f"-c search_path={SCHEMA}"},
    )


async def connection_slot() -> AsyncIterator[None]:
    """Wait, without holding a thread, until one of the pool's connections is free.

    A request holds its connection across more than one of FastAPI's threads. If
    requests waited for a connection inside a thread, they could take every thread
    while the requests holding the connections wait for one to finish.
    """
    async with CONNECTION_SLOTS:
        yield


def database(
    _: Annotated[None, Depends(connection_slot)],
) -> Iterator[Connection]:
    """Open a connection for one request and commit if the request succeeds."""
    with engine().begin() as connection:
        yield connection


Database = Annotated[Connection, Depends(database)]


def now() -> str:
    """Return the current time in UTC, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")
