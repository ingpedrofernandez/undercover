"""The UnderCover Agent's claim agent, which works one claim from a clean start."""

import json
import os
import uuid
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from agent.tools import REFUSED, TOOLS, request

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
TIMEOUT_SECONDS = 120
RETRIES = 2
RETRY_DELAY_SECONDS = 1.0
CLAIM_MODEL_CALLS = 30


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
    )


def harness(model_calls: int) -> list[AgentMiddleware[Any, Any, Any]]:
    """Retry a failed model call with backoff, and stop an agent after model_calls."""
    return [
        ModelRetryMiddleware(
            max_retries=RETRIES, initial_delay=RETRY_DELAY_SECONDS, on_failure="error"
        ),
        ModelCallLimitMiddleware(run_limit=model_calls, exit_behavior="error"),
    ]


class BackendError(Exception):
    """The backend refused a request the agent's run depends on."""


def call_backend(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Call the backend and return its JSON, raising if it refuses."""
    response = request(method, path, body)
    if response.is_error:
        raise BackendError(f"{response.status_code}: {response.json()['detail']}")
    return response.json()


def steps(message: AnyMessage) -> list[tuple[str, str]]:
    """Turn one message from the agent's run into steps for the dashboard."""
    if isinstance(message, ToolMessage):
        if message.name == "read_section" and not message.text.startswith(REFUSED):
            return [("read", message.text)]
        return [("tool_result", f"{message.name}: {message.text}")]
    found = []
    if message.text:
        found.append(("message", message.text))
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in call["args"].items())
            found.append(("tool_call", f"{call['name']}({args})"))
    return found


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Work a started claim, recording each step, and return the reply."""
    instructions = call_backend("GET", "/api/instructions")["claim"]
    agent = create_agent(
        llm or model(),
        tools=TOOLS,
        system_prompt=instructions,
        middleware=harness(CLAIM_MODEL_CALLS),
        checkpointer=InMemorySaver(),
    )
    states = agent.stream(
        {"messages": [{"role": "user", "content": f"Claim {claim_id}"}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="values",
    )
    messages = next(states)["messages"]
    for state in states:
        for message in state["messages"][len(messages) :]:
            for kind, content in steps(message):
                call_backend(
                    "POST",
                    f"/api/claims/{claim_id}/steps",
                    {"kind": kind, "content": content},
                )
        messages = state["messages"]
    return messages[-1].text


def report(claim: dict[str, Any]) -> str:
    """Describe a claim's outcome in one line, from the backend's record."""
    decision = claim["decision"]
    line = f"{claim['claim_id']}  {decision['decision']}  ${decision['payout']:,.2f}"
    if claim["status"] == "waiting_for_sign_off":
        return f"{line}  waiting for sign-off"
    if decision["decision"] == "approve":
        return f"{line}  {'paid' if claim['payment'] else 'not paid'}"
    return line


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Start a claim and work it, putting it right if it fails, and report one line."""
    thread_id = str(uuid.uuid4())
    started = request("POST", f"/api/claims/{claim_id}/start", {"thread_id": thread_id})
    if started.is_error:
        return f"{claim_id}  not started: {started.json()['detail']}"
    try:
        run(claim_id, thread_id, llm)
        problem = "The claim agent finished without recording a decision"
    except Exception as error:  # one failed claim must never stop the queue
        problem = f"{type(error).__name__}: {error}".splitlines()[0]
    claim = call_backend("GET", f"/api/claims/{claim_id}")
    if claim["status"] != "in_progress":
        return report(claim)
    claim = call_backend("POST", f"/api/claims/{claim_id}/failure", {"reason": problem})
    problem = problem.rstrip(".")
    if claim["status"] == "left_for_handler":
        return f"{claim_id}  failed again: {problem}. Left for a handler."
    return f"{claim_id}  failed: {problem}. Back in the queue."


def work_queue() -> None:
    """Work every waiting claim in queue order, printing a line for each."""
    claims = call_backend("GET", "/api/claims")
    waiting = [claim["claim_id"] for claim in claims if claim["status"] == "waiting"]
    for claim_id in waiting:
        print(work_claim(claim_id), flush=True)
    print(f"Worked {len(waiting)} claims")
