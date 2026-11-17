"""The agent's web service: it starts dispatches, and carries a claim on as soon as a
handler signs it off. It hands each request on and does no work itself.

npm run dev starts it on port 8002, with .env.
"""

import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent import harness, work

ONE_CLAIM_AT_A_TIME = threading.Lock()
ONE_RUN_AT_A_TIME = threading.Lock()
RESUMING: set[str] = set()

Agents = Annotated[
    int, Field(ge=1, le=25, description="How many claim agents work at once")
]


class DispatchRequest(BaseModel):
    agents: Agents


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Open the pool, so the first claim doesn't wait for it, and mark any run an
    earlier process left running as stopped."""
    harness.pool()
    work.stop_unfinished_runs()
    yield


app = FastAPI(title="UnderCover Agent", lifespan=lifespan)


def resume(claim_id: str) -> None:
    """Carry a claim on, one claim at a time, and print its line."""
    try:
        with ONE_CLAIM_AT_A_TIME:
            print(harness.work_claim(claim_id, None), flush=True)
    finally:
        RESUMING.discard(claim_id)


def run_then_release(run: Callable[..., None], *args: object) -> None:
    """Do a dispatch, then let the next one start."""
    try:
        run(*args)
    finally:
        ONE_RUN_AT_A_TIME.release()


def start(background: BackgroundTasks, run: Callable[..., None], *args: object) -> None:
    """Start a run in the background, or refuse with a 409 while one is going."""
    if not ONE_RUN_AT_A_TIME.acquire(blocking=False):
        raise HTTPException(409, "A dispatch or evaluation is already running")
    background.add_task(run_then_release, run, *args)


@app.post("/api/claims/{claim_id}/resume", operation_id="resume_claim", status_code=202)
def resume_claim(claim_id: str, background: BackgroundTasks) -> dict[str, str]:
    """Carry a claim on from where it stopped, in the background."""
    RESUMING.add(claim_id)
    background.add_task(resume, claim_id)
    return {"status": "accepted"}


@app.post("/api/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(
    request: DispatchRequest, background: BackgroundTasks
) -> dict[str, str]:
    """Start a dispatch over the queue in the background, unless a run is going."""
    start(background, work.dispatch, request.agents, sorted(RESUMING))
    return {"status": "accepted"}


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}
