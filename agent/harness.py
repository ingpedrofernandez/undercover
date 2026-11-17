"""The harness around the claim agent: the model, the claim graph and its nodes,
the checkpointer, tracing, and work_claim, the one way to work a claim with it."""

import contextvars
import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache, partial
from typing import Annotated, Any, NotRequired, TypedDict, cast
from uuid import UUID

from langchain.agents.middleware import ToolCallRequest
from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableConfig
from langchain_deepseek import ChatDeepSeek
from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy, interrupt
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool
from pydantic import SecretStr

from agent import api
from agent.tools import CLAIM_TOOLS

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-luna"
TIMEOUT_SECONDS = 120
RETRIES = 2
RETRY_DELAY_SECONDS = 1.0
CLAIM_MODEL_CALLS = 30
SCHEMA = "undercover"
CONNECTIONS = 4
CONNECTION_WAIT_SECONDS = 600
UNSETTLED = (ModelRateLimitError, ModelTimeoutError)

Agent = CompiledStateGraph[Any, Any, Any, Any]


def model_settings() -> tuple[str, str]:
    """Return the model's name and reasoning effort: GPT-6 Luna at low by default,
    or the model named in MODEL_NAME with none."""
    name = os.getenv("MODEL_NAME")
    return (name, "none") if name else (DEFAULT_MODEL, "low")


def model() -> ChatDeepSeek:
    """Return the model in model_settings, through OpenRouter.

    ChatDeepSeek keeps the reasoning OpenRouter sends, which ChatOpenAI drops,
    so the traces show why the model did what it did.
    """
    name, effort = model_settings()
    return ChatDeepSeek(
        model=name,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if effort == "none" else effort,
        timeout=TIMEOUT_SECONDS,
        max_retries=0,
    )


def refusal(error: Exception) -> str | None:
    """Word a backend refusal for the model, or return None for any other error."""
    return f"Refused: {error}" if isinstance(error, api.ApiError) else None


def call_text(name: str, args: dict[str, Any]) -> str:
    """Write a tool call as the dashboard shows it: get_claim(claim_id="CLM-1001")."""
    return f"{name}({', '.join(f'{k}={json.dumps(v)}' for k, v in args.items())})"


def steps(message: AnyMessage) -> list[tuple[str, str]]:
    """Turn one message of a claim agent's work into steps for the dashboard."""
    if isinstance(message, ToolMessage):
        if message.name == "read_section" and message.status == "success":
            return [("read", message.text)]
        return [("tool_result", f"{message.name}: {message.text}")]
    found = []
    if message.text:
        found.append(("message", message.text))
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            found.append(("tool_call", call_text(call["name"], call["args"])))
    return found


def record_steps(claim_id: str, message: AnyMessage) -> None:
    """Record a message of a claim agent's work as steps on its claim."""
    for kind, content in steps(message):
        api.record_step(claim_id, kind, content)


class ClaimState(TypedDict):
    """What the claim graph keeps for one try at a claim, saved after every step."""

    messages: Annotated[list[AnyMessage], add_messages]
    claim_id: str
    model_calls: int
    signed_off_by: NotRequired[str]


@dataclass
class ClaimContext:
    """What one run of the claim graph knows besides its state: the run it is in."""

    run_id: int | None


class ModelCallLimitExceeded(Exception):
    """A claim agent used all its model calls without finishing."""


def record_model_call(claim_id: str, run_id: int | None, reply: AnyMessage) -> None:
    """Record the tokens and cost OpenRouter reports for one model reply."""
    usage = reply.response_metadata["token_usage"]
    api.record_model_call(
        claim_id,
        run_id,
        usage["prompt_tokens"],
        usage["completion_tokens"],
        usage["cost"],
    )


def tool_error(error: api.ApiError | ToolInvocationError) -> str:
    """Hand a backend refusal, or a call with the wrong arguments, back to the model."""
    return refusal(error) or str(error)


def record_tool_result(
    request: ToolCallRequest, execute: Callable[[ToolCallRequest], Any]
) -> Any:
    """Run one tool call and record its result on the claim."""
    result = execute(request)
    if isinstance(result, ToolMessage):
        record_steps(request.state["claim_id"], result)
    return result


def can_retry(error: Exception) -> bool:
    """Retry a failed model call, but not a claim agent out of model calls."""
    return not isinstance(error, ModelCallLimitExceeded)


def after_agent(state: ClaimState) -> str:
    """Run the tools the model asked for, or go where the backend's record says."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    claim = api.get_claim(state["claim_id"])
    if claim["status"] == "waiting_for_sign_off":
        return "sign_off"
    decision = claim["decision"]
    if decision and decision["decision"] == "approve" and not claim["payment"]:
        return "pay"
    return END


def sign_off(state: ClaimState) -> dict[str, str]:
    """Wait for a handler to sign off the held payout, then note who did."""
    claim = api.get_claim(state["claim_id"])
    answer = interrupt(
        {"claim_id": claim["claim_id"], "payout": claim["decision"]["payout"]}
    )
    return {"signed_off_by": answer["signed_off_by"]}


def pay(state: ClaimState) -> None:
    """Pay the approved payout through the backend, which pays a claim only once."""
    claim_id = state["claim_id"]
    payout = api.get_claim(claim_id)["decision"]["payout"]
    call = call_text("pay_claim", {"claim_id": claim_id, "amount": payout})
    api.record_step(claim_id, "tool_call", call)
    paid = api.pay_claim(claim_id, payout)
    api.record_step(claim_id, "tool_result", f"pay_claim: {json.dumps(paid)}")


def claim_graph(llm: BaseChatModel | None = None) -> Agent:
    """Build the claim graph, which works one claim, waits for a handler when the
    backend holds the payout, and pays an approval."""
    chat = (llm or model()).bind_tools(CLAIM_TOOLS)
    instructions = SystemMessage(api.get_instructions()["claim"])

    def agent(state: ClaimState, runtime: Runtime[ClaimContext]) -> dict[str, Any]:
        """Call the model with the conversation so far, and record its reply and
        what it cost."""
        calls = state["model_calls"]
        if calls >= CLAIM_MODEL_CALLS:
            raise ModelCallLimitExceeded(
                f"The claim agent made {calls} model calls without finishing"
            )
        reply = chat.invoke([instructions, *state["messages"]])
        record_steps(state["claim_id"], reply)
        record_model_call(state["claim_id"], runtime.context.run_id, reply)
        return {"messages": [reply], "model_calls": calls + 1}

    retry = RetryPolicy(
        max_attempts=RETRIES + 1,
        initial_interval=RETRY_DELAY_SECONDS,
        jitter=False,
        retry_on=can_retry,
    )
    tools = ToolNode(
        CLAIM_TOOLS, handle_tool_errors=tool_error, wrap_tool_call=record_tool_result
    )
    builder = StateGraph(ClaimState, context_schema=ClaimContext)
    builder.add_node("agent", agent, retry_policy=retry)
    builder.add_node("tools", tools)
    builder.add_node("sign_off", sign_off)
    builder.add_node("pay", pay)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent", after_agent, ["tools", "sign_off", "pay", END]
    )
    builder.add_edge("tools", "agent")
    builder.add_edge("sign_off", "pay")
    builder.add_edge("pay", END)
    return builder.compile(checkpointer=checkpointer(), name="claim-agent")


@cache
def pool() -> ConnectionPool[Connection[DictRow]]:
    """Return the process's one pool of connections to Supabase, with the
    checkpointer's tables set up.

    It uses the lab's settings, the undercover schema and at most four connections.
    A claim waits for a free connection rather than fail.
    """
    connections = ConnectionPool[Connection[DictRow]](
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=CONNECTIONS,
        timeout=CONNECTION_WAIT_SECONDS,
        open=True,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": f"-c search_path={SCHEMA}",
        },
    )
    PostgresSaver(connections).setup()
    return connections


def checkpointer() -> BaseCheckpointSaver[str]:
    """Return a saver of its own for one claim graph, on the process's one pool.

    A PostgresSaver holds a lock around every read and write, so one saver shared
    by every claim agent would make them take turns.
    """
    return PostgresSaver(pool())


def clear_progress(thread_id: str) -> None:
    """Delete everything saved on a claim's thread, so it is never carried on."""
    checkpointer().delete_thread(thread_id)


def thread(thread_id: str) -> RunnableConfig:
    """Return the config that runs the claim graph on one claim's thread."""
    return RunnableConfig(
        configurable={"thread_id": thread_id},
        callbacks=[tracing()],
        recursion_limit=3 * CLAIM_MODEL_CALLS,
    )


def claim_task(claim_id: str) -> dict[str, Any]:
    """Return the claim graph's input for a claim worked from the start."""
    return {
        "messages": [HumanMessage(f"Claim {claim_id}")],
        "claim_id": claim_id,
        "model_calls": 0,
    }


def carry_on_input(graph: Agent, claim: dict[str, Any]) -> Any:
    """Return what carries a claim's thread on from where it stopped.

    A thread with no step saved starts from the task. One waiting at the sign-off
    resumes with the handler's name once the backend has the sign-off. Any other
    carries on from its last saved step, which does nothing once it has finished.
    """
    saved = graph.get_state(thread(claim["thread_id"]))
    if not saved.values:
        return claim_task(claim["claim_id"])
    signed_off_by = claim["decision"] and claim["decision"]["signed_off_by"]
    if saved.interrupts and signed_off_by:
        return Command(resume={"signed_off_by": signed_off_by})
    return None


def run_claim_graph(
    graph: Agent, start: Any, thread_id: str, run_id: int | None
) -> None:
    """Run the claim graph on a thread in a run, saving each step before the next
    starts. The claim's trace is tagged with the run, so a whole run can be found
    together in Langfuse."""
    config = thread(thread_id)
    if run_id is not None:
        config["metadata"] = {"langfuse_tags": [f"run-{run_id}"]}
    graph.invoke(start, config, context=ClaimContext(run_id), durability="sync")


class Tracing(CallbackHandler):
    """Langfuse's LangChain handler, which also records what OpenRouter charged."""

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> Any:
        """Put OpenRouter's cost on the model call's generation, then end it.

        The generation is the current observation until Langfuse's handler ends it.
        """
        cost = cast(dict[str, Any], response.llm_output)["token_usage"]["cost"]
        get_client().update_current_generation(cost_details={"total": cost})
        return super().on_llm_end(
            response, run_id=run_id, parent_run_id=parent_run_id, **kwargs
        )


@cache
def tracing() -> Tracing:
    """Return the one Langfuse handler that traces every agent run."""
    return Tracing()


def trace_claim(claim_id: str, thread_id: str, work: Callable[[], str]) -> str:
    """Do one piece of work on a claim as a work-claim trace of its own.

    The trace is in the session of the claim's thread, so everything that happens
    on one try at a claim reads as one story. A trace can only be in one session,
    so the work runs in a fresh context: a claim worked in a run starts a trace of
    its own rather than nesting under the run's.
    """
    return contextvars.Context().run(in_claim_trace, claim_id, thread_id, work)


def in_claim_trace(claim_id: str, thread_id: str, work: Callable[[], str]) -> str:
    """Do the work inside a new work-claim trace, and return its line."""
    with (
        get_client().start_as_current_observation(
            name="work-claim", input=claim_id
        ) as span,
        propagate_attributes(session_id=f"{claim_id}:{thread_id}"),
    ):
        line = work()
        span.update(output=line)
    return line


def report(claim: dict[str, Any]) -> str:
    """Describe a decided claim in one line, from the backend's record."""
    decision = claim["decision"]
    line = f"{claim['claim_id']}  {decision['decision']}  ${decision['payout']:,.2f}"
    if claim["status"] == "waiting_for_sign_off":
        return f"{line}  waiting for sign-off"
    if decision["decision"] == "approve":
        return f"{line}  {'paid' if claim['payment'] else 'not paid'}"
    return line


def outcome(claim_id: str, run: Callable[[], None]) -> str:
    """Run the claim graph, put the claim right if it fails, and report one line."""
    try:
        run()
        problem = "The claim agent finished without recording a decision"
    except UNSETTLED:
        raise  # the caller waits and carries the claim on, as the same try
    except Exception as error:  # one failed claim must never stop the others
        problem = f"{type(error).__name__}: {error}".splitlines()[0]
    claim = api.get_claim(claim_id)
    if claim["decision"] is not None:
        return report(claim)
    claim = api.record_failure(claim_id, problem)
    problem = problem.rstrip(".")
    if claim["status"] == "left_for_handler":
        return f"{claim_id}  failed again: {problem}. Left for a handler."
    return f"{claim_id}  failed: {problem}. Back in the queue."


def timed(claim_id: str, run_id: int | None, work: Callable[[], str]) -> str:
    """Do one piece of work on a claim, and record how long it took with the run."""
    started = datetime.now(UTC).isoformat(timespec="seconds")
    clock = time.monotonic()
    try:
        return work()
    finally:
        api.record_work_time(claim_id, run_id, started, time.monotonic() - clock)


def take_up(graph: Agent, claim: dict[str, Any]) -> tuple[str, Any]:
    """Return the thread a claim is worked on and what starts the graph there.

    A claim in progress carries on its own thread, as the same try. A waiting
    claim is started on a new thread.
    """
    if claim["status"] == "in_progress":
        return claim["thread_id"], carry_on_input(graph, claim)
    thread_id = str(uuid.uuid4())
    api.start_claim(claim["claim_id"], thread_id)
    return thread_id, claim_task(claim["claim_id"])


def work_claim(
    claim_id: str, run_id: int | None, llm: BaseChatModel | None = None
) -> str:
    """Carry a claim in progress on, or start a waiting one, and report one line.

    This is the one way to work a claim with the claim agent. The time it takes
    is recorded with the run, or with none when run_id is None. A rate limit or a
    timeout is raised without settling the claim, so it stays in progress and
    carries on from its last saved step when worked again.
    """
    claim = api.get_claim(claim_id)
    graph = claim_graph(llm)
    thread_id, start = take_up(graph, claim)
    run = partial(run_claim_graph, graph, start, thread_id, run_id)
    work = partial(timed, claim_id, run_id, partial(outcome, claim_id, run))
    return trace_claim(claim_id, thread_id, work)
