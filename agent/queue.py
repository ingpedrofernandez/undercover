"""The UnderCover Agent's queue agent, which plans a run and hands each claim over."""

import threading
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool
from langgraph.runtime import Runtime
from pydantic import BaseModel

from agent import main
from agent.tools import reply, request

QUEUE_MODEL_CALLS = 200


class Todo(BaseModel):
    """One item on the queue agent's to-do list."""

    content: str
    status: Literal["to_do", "in_progress", "done", "left_for_handler"]


class QueueRun:
    """One run over the queue: its id, its cap and the claims it has taken on."""

    def __init__(self, run_id: int, limit: int, claim_llm: BaseChatModel | None):
        self.run_id = run_id
        self.limit = limit
        self.claim_llm = claim_llm
        self.taken: set[str] = set()
        self.lock = threading.Lock()

    def work_claim(self, claim_id: str) -> str:
        """Hand a claim to the claim agent, one at a time and within the cap."""
        with self.lock:
            if claim_id not in self.taken and len(self.taken) >= self.limit:
                cap = f"the run's cap of {self.limit} claims is reached"
                line = main.not_started(claim_id, cap)
            else:
                line = main.work_claim(claim_id, self.claim_llm)
                if not line.startswith(f"{claim_id}  {main.NOT_STARTED}"):
                    self.taken.add(claim_id)
        print(line, flush=True)
        return line

    def missed(self) -> list[str]:
        """Return the waiting claims this run should still work."""
        claims = main.call_backend("GET", "/api/claims")
        waiting = [c["claim_id"] for c in claims if c["status"] == "waiting"]
        retries = [claim_id for claim_id in waiting if claim_id in self.taken]
        room = self.limit - len(self.taken)
        others = [claim_id for claim_id in waiting if claim_id not in self.taken]
        return retries + others[: max(room, 0)]


class MissedClaimsCheck(AgentMiddleware):
    """Send the queue agent back to work if it tries to finish with claims missed."""

    def __init__(self, run: QueueRun):
        super().__init__()
        self.run = run

    @hook_config(can_jump_to=["model"])
    def after_model(
        self, state: AgentState, runtime: Runtime[None]
    ) -> dict[str, Any] | None:
        """Check the queue when the agent replies without calling a tool."""
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or last.tool_calls:
            return None
        missed = self.run.missed()
        if not missed:
            return None
        note = (
            "Before you finish: these claims are still waiting within this run's"
            f" cap: {', '.join(missed)}. Work them, then finish with your summary."
        )
        return {"messages": [HumanMessage(note)], "jump_to": "model"}


def queue_tools(run: QueueRun) -> list[BaseTool]:
    """Make the queue agent's tools for one run."""

    @tool
    def list_claims() -> str:
        """List every claim in the queue with its status, decision and payout."""
        return reply(request("GET", "/api/claims"))

    @tool
    def write_todos(todos: list[Todo]) -> str:
        """Save your whole to-do list for this run, which the claims team watches."""
        body = {"todos": [todo.model_dump() for todo in todos]}
        response = request("PUT", f"/api/runs/{run.run_id}/todos", body)
        return reply(response) if response.is_error else f"Saved {len(todos)} items."

    @tool
    def work_claim(claim_id: str) -> str:
        """Hand one claim to a claim agent, which works it from a clean start."""
        return run.work_claim(claim_id)

    return [list_claims, write_todos, work_claim]


def run_queue(
    limit: int,
    llm: BaseChatModel | None = None,
    claim_llm: BaseChatModel | None = None,
) -> str:
    """Start a run capped at limit claims, have the queue agent work it, finish it."""
    run_id = main.call_backend("POST", "/api/runs", {"limit": limit})["run_id"]
    print(f"Run {run_id} started, capped at {limit} claims", flush=True)
    run = QueueRun(run_id, limit, claim_llm)
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        *main.harness(QUEUE_MODEL_CALLS),
        MissedClaimsCheck(run),
    ]
    agent = create_agent(
        llm or main.model(),
        tools=queue_tools(run),
        system_prompt=main.call_backend("GET", "/api/instructions")["queue"],
        middleware=middleware,
    )
    task = f"Run {run_id}. Work the claims queue, taking on at most {limit} claims."
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": task}]})
        summary = result["messages"][-1].text or "The run finished without a summary."
    except Exception as error:  # a run must always be finished
        summary = f"The run stopped early: {type(error).__name__}: {error}"
    main.call_backend("POST", f"/api/runs/{run_id}/finish", {"summary": summary})
    return summary
