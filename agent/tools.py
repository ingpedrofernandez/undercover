"""Every tool the UnderCover Agent uses, named after the backend operations."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import BaseModel

from agent import api

DOCUMENT_NAMES = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}

Document = Literal["policy_wording", "claims_manual"]

ONE_CLAIM_AT_A_TIME = threading.Lock()


class Todo(BaseModel):
    """One item on the queue agent's to-do list."""

    content: str
    status: Literal["to_do", "in_progress", "done", "left_for_handler"]


@dataclass
class RunContext:
    """The run the queue agent is working, which its tools reach through ToolRuntime."""

    run_id: int
    limit: int
    work_claim: Callable[[str], str]
    taken: set[str] = field(default_factory=set)


@tool
def get_claim(claim_id: str) -> dict[str, Any]:
    """Get one claim in full: the story, the items claimed and the documents."""
    return api.get_claim(claim_id)


@tool
def get_policy(policy_id: str) -> dict[str, Any]:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return api.get_policy(policy_id)


@tool
def get_claim_history(customer_id: str) -> list[dict[str, Any]]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    return api.get_claim_history(customer_id)


@tool
def list_sections(document: Document) -> list[dict[str, Any]]:
    """List the numbered sections of the policy wording or the claims manual."""
    return api.list_sections(document)


@tool
def search_documents(query: str) -> list[dict[str, Any]]:
    """Find the sections of both documents with a line containing a word or phrase."""
    return api.search_documents(query)


@tool
def read_section(document: Document, section: int) -> str:
    """Read one section of the policy wording or the claims manual in full."""
    found = api.read_section(document, section)
    name = DOCUMENT_NAMES[document]
    return f"{name}, section {section}: {found['title']}\n\n{found['text']}"


@tool
def record_decision(
    claim_id: str,
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    section: str,
    reason: str,
) -> dict[str, Any]:
    """Record the decision on a claim; an approval over the limit waits for sign-off."""
    return api.record_decision(claim_id, decision, payout, section, reason)


@tool
def pay_claim(claim_id: str, amount: float) -> dict[str, Any]:
    """Pay an approved claim its payout, unless it needs a handler's sign-off."""
    return api.pay_claim(claim_id, amount)


@tool
def list_claims() -> list[dict[str, Any]]:
    """List every claim in the queue with its status, decision and payout."""
    return api.list_claims()


@tool
def write_todos(todos: list[Todo], runtime: ToolRuntime[RunContext]) -> str:
    """Save your whole to-do list for this run, which the claims team watches."""
    api.write_todos(runtime.context.run_id, [todo.model_dump() for todo in todos])
    return f"Saved {len(todos)} items."


@tool
def work_claim(claim_id: str, runtime: ToolRuntime[RunContext]) -> str:
    """Hand one claim to a claim agent, which works it and reports back in a line."""
    run = runtime.context
    with ONE_CLAIM_AT_A_TIME:  # the model can ask for several claims in one turn
        if claim_id not in run.taken and len(run.taken) >= run.limit:
            cap = f"the run's cap of {run.limit} claims is reached"
            return f"{claim_id}  not started: {cap}"
        line = run.work_claim(claim_id)
        run.taken.add(claim_id)
        return line


CLAIM_TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    list_sections,
    search_documents,
    read_section,
    record_decision,
    pay_claim,
]
QUEUE_TOOLS = [list_claims, write_todos, work_claim]
