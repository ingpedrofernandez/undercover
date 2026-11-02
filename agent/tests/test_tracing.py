import sqlite3
from contextlib import closing

from agent import work
from agent.tests.test_agent import StubModel, script
from agent.tests.test_queue import asks_for, queue_agent

TYPE = "langfuse.observation.type"
INPUT = "langfuse.observation.input"
OUTPUT = "langfuse.observation.output"
COST = "langfuse.observation.cost_details"


class PricedModel(StubModel):
    """A stub model whose replies carry the cost OpenRouter reports."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(messages, stop, run_manager, **kwargs)
        result.llm_output = {"token_usage": {"total_tokens": 49, "cost": 0.0000043}}
        return result


def named(spans, name):
    return [span for span in spans if span.name == name]


def parent(spans, span):
    return next(s for s in spans if s.context.span_id == span.parent.span_id)


def test_a_claim_on_its_own_is_one_trace(client, spans):
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    assert work.work_one_claim("CLM-1001", stub) == "CLM-1001  decline  $0.00"

    traced = spans()
    [root] = named(traced, "work-claim")
    assert root.parent is None
    assert root.attributes[INPUT] == "CLM-1001"
    assert root.attributes[OUTPUT] == "CLM-1001  decline  $0.00"
    [agent] = named(traced, "claim-agent")
    assert agent.attributes[TYPE] == "agent"
    assert parent(traced, agent) == root
    assert {s.attributes[TYPE] for s in named(traced, "StubModel")} == {"generation"}
    assert named(traced, "record_decision")[0].attributes[TYPE] == "tool"


def test_a_run_traces_each_claim_agent_once_under_its_call(client, database, spans):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE claims SET status = 'decided' WHERE claim_id != 'CLM-1001'")
    claim = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    work.run_queue(1, queue_agent(*asks_for("CLM-1001")), claim)

    traced = spans()
    [root] = named(traced, "run-queue")
    assert root.parent is None
    assert root.attributes[INPUT].startswith("Run 1. Work the claims queue")
    assert root.attributes[OUTPUT] == "The summary."
    [queue] = named(traced, "queue-agent")
    assert queue.attributes[TYPE] == "agent"
    assert parent(traced, queue) == root
    [agent] = named(traced, "claim-agent")
    assert parent(traced, agent) == named(traced, "work_claim")[0]
    assert len(named(traced, "get_claim")) == 1
    assert {s.context.trace_id for s in traced} == {root.context.trace_id}


def test_each_model_call_records_what_openrouter_charged(client, spans):
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    work.work_one_claim("CLM-1001", PricedModel(messages=stub.messages))

    generations = named(spans(), "PricedModel")
    assert len(generations) == 5
    assert {span.attributes[COST] for span in generations} == {'{"total": 4.3e-06}'}


def test_a_model_call_without_a_cost_records_none(client, spans):
    work.work_one_claim(
        "CLM-1001", script("CLM-1001", "POL-2001", "CUS-3001", "refer", 0)
    )

    assert all(COST not in span.attributes for span in named(spans(), "StubModel"))
