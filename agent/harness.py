"""The harness around both agents: the model, their middleware and running them."""

import os
from collections.abc import Callable
from functools import cache
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallRequest,
    ToolErrorMiddleware,
    hook_config,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_deepseek import ChatDeepSeek
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from pydantic import SecretStr

from agent import api
from agent.tools import CLAIM_TOOLS, QUEUE_TOOLS, RunContext

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
TIMEOUT_SECONDS = 120
RETRIES = 2
RETRY_DELAY_SECONDS = 1.0
CLAIM_MODEL_CALLS = 30
QUEUE_MODEL_CALLS = 200

Agent = CompiledStateGraph[Any, Any, Any, Any]


def model() -> ChatDeepSeek:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default.

    ChatDeepSeek keeps the reasoning OpenRouter sends, which ChatOpenAI drops,
    so the traces show why the model did what it did.
    """
    name = os.getenv("MODEL_NAME")
    return ChatDeepSeek(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
    )


def refused(error: Exception, request: ToolCallRequest) -> str | None:
    """Hand a backend refusal back to the model, so the agent can carry on."""
    return f"Refused: {error}" if isinstance(error, api.ApiError) else None


def middleware(model_calls: int) -> list[AgentMiddleware[Any, Any, Any]]:
    """Retry failed model calls, return refusals to the model and cap model calls."""
    return [
        ModelRetryMiddleware(
            max_retries=RETRIES, initial_delay=RETRY_DELAY_SECONDS, on_failure="error"
        ),
        ModelCallLimitMiddleware(run_limit=model_calls, exit_behavior="error"),
        ToolErrorMiddleware(refused),
    ]


def missed_claims(run: RunContext) -> list[str]:
    """Return the waiting claims a run should still work, retries first."""
    waiting = [c["claim_id"] for c in api.list_claims() if c["status"] == "waiting"]
    retries = [claim_id for claim_id in waiting if claim_id in run.taken]
    others = [claim_id for claim_id in waiting if claim_id not in run.taken]
    return retries + others[: max(run.limit - len(run.taken), 0)]


class MissedClaimsCheck(AgentMiddleware[AgentState, RunContext, Any]):
    """Send the queue agent back to work if it tries to finish with claims missed."""

    @hook_config(can_jump_to=["model"])
    def after_model(
        self, state: AgentState, runtime: Runtime[RunContext]
    ) -> dict[str, Any] | None:
        """Check the queue when the agent replies without calling a tool."""
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or last.tool_calls:
            return None
        missed = missed_claims(runtime.context)
        if not missed:
            return None
        note = (
            "Before you finish: these claims are still waiting within this run's"
            f" cap: {', '.join(missed)}. Work them, then finish with your summary."
        )
        return {"messages": [HumanMessage(note)], "jump_to": "model"}


def claim_agent(llm: BaseChatModel | None = None) -> Agent:
    """Build a claim agent, which works one claim from a clean start."""
    return create_agent(
        llm or model(),
        tools=CLAIM_TOOLS,
        system_prompt=api.get_instructions()["claim"],
        middleware=middleware(CLAIM_MODEL_CALLS),
        checkpointer=InMemorySaver(),
        name="claim-agent",
    )


def queue_agent(llm: BaseChatModel | None = None) -> Agent:
    """Build the queue agent, which plans a run and hands each claim over."""
    return create_agent(
        llm or model(),
        tools=QUEUE_TOOLS,
        system_prompt=api.get_instructions()["queue"],
        middleware=[*middleware(QUEUE_MODEL_CALLS), MissedClaimsCheck()],
        context_schema=RunContext,
        name="queue-agent",
    )


@cache
def tracing() -> CallbackHandler:
    """Return the one Langfuse handler that traces every agent run.

    A claim agent run inside the queue agent's tool call inherits the queue
    agent's handler. Sharing one handler means it is traced once, under that call.
    """
    return CallbackHandler()


def run_agent(
    agent: Agent,
    task: str,
    on_message: Callable[[AnyMessage], None],
    **options: Any,
) -> str:
    """Run an agent on a task, traced in Langfuse, and return its reply.

    Each new message is passed on to on_message as it arrives.
    """
    traced = agent.with_config(callbacks=[tracing()])
    states = traced.stream(
        {"messages": [HumanMessage(task)]}, stream_mode="values", **options
    )
    messages = next(states)["messages"]
    for state in states:
        for message in state["messages"][len(messages) :]:
            on_message(message)
        messages = state["messages"]
    return messages[-1].text
