"""The agent's web service, which carries a claim on as soon as a handler signs it off.

npm run dev starts it on port 8002, with .env.
"""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI

from agent import harness

ONE_CLAIM_AT_A_TIME = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Open the checkpointer on startup, so the first claim doesn't wait for it."""
    harness.checkpointer()
    yield


app = FastAPI(title="UnderCover Agent", lifespan=lifespan)


def resume(claim_id: str) -> None:
    """Carry a claim on, one claim at a time, and print its line."""
    with ONE_CLAIM_AT_A_TIME:
        print(harness.work_claim(claim_id, None), flush=True)


@app.post("/api/claims/{claim_id}/resume", operation_id="resume_claim", status_code=202)
def resume_claim(claim_id: str, background: BackgroundTasks) -> dict[str, str]:
    """Carry a claim on from where it stopped, in the background."""
    background.add_task(resume, claim_id)
    return {"status": "accepted"}


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}
