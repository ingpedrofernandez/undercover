"""The UnderCover backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import inspect

from backend import claims, documents, evaluations, payouts, records, runs, usage
from backend.database import engine
from backend.seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed the database on startup if it has no claims yet."""
    if not inspect(engine()).has_table("claims"):
        seed()
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)
for module in (claims, usage, records, payouts, documents, runs, evaluations):
    app.include_router(module.router)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}
