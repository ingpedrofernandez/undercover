"""The UnderCover backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import claims, documents, records, runs
from backend.database import database_path
from backend.seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed the database on startup if it doesn't exist yet."""
    if not database_path().exists():
        seed(database_path())
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)
for module in (claims, records, documents, runs):
    app.include_router(module.router)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}
