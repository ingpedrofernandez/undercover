import sqlite3
from contextlib import closing

from agent import work
from agent.tests.test_agent import StubModel, script
from agent.tests.test_queue import asks_for, queue_agent

TYPE = "langfuse.observation.type"
SESSION = "session.id"
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


def in_trace(spans, root):
    return [s for s in spans if s.context.trace_id == root.context.trace_id]


def thread_of(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()["thread_id"]


def test_a_claim_on_its_own_is_one_trace_in_its_session(client, spans):
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    assert work.work_claim("CLM-1001", stub) == "CLM-1001  decline  $0.00"

    traced = spans()
    [root] = named(traced, "work-claim")
    assert root.parent is None
    assert root.attributes[INPUT] == "CLM-1001"
    assert root.attributes[OUTPUT] == "CLM-1001  decline  $0.00"
    assert in_trace(traced, root) == list(traced)
    session = f"CLM-1001:{thread_of(client, 'CLM-1001')}"
    assert {s.attributes[SESSION] for s in traced} == {session}
    [agent] = named(traced, "claim-agent")
    assert agent.attributes[TYPE] == "agent"
    assert parent(traced, agent) == root
    assert {s.attributes[TYPE] for s in named(traced, "StubModel")} == {"generation"}
    assert named(traced, "record_decision")[0].attributes[TYPE] == "tool"


def test_a_run_traces_each_claim_on_its_own(client, database, spans):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE claim_id NOT IN ('CLM-1001', 'CLM-1003')"
        )
    first = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    second = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    both = StubModel(messages=iter([*first.messages, *second.messages]))
    work.run_queue(2, queue_agent(*asks_for("CLM-1001", "CLM-1003")), both)

    traced = spans()
    [root] = named(traced, "run-queue")
    assert root.parent is None
    assert root.attributes[INPUT].startswith("Run 1. Work the claims queue")
    assert root.attributes[OUTPUT] == "The summary."
    run = in_trace(traced, root)
    [queue] = named(run, "queue-agent")
    assert queue.attributes[TYPE] == "agent"
    assert parent(traced, queue) == root
    assert len(named(run, "work_claim")) == 2
    assert named(run, "claim-agent") == []
    assert all(SESSION not in s.attributes for s in run)

    claims = named(traced, "work-claim")
    assert [c.attributes[INPUT] for c in claims] == ["CLM-1001", "CLM-1003"]
    assert all(claim.parent is None for claim in claims)
    for claim in claims:
        claim_id = claim.attributes[INPUT]
        own = in_trace(traced, claim)
        assert len(named(own, "claim-agent")) == 1
        assert len(named(own, "get_claim")) == 1
        session = f"{claim_id}:{thread_of(client, claim_id)}"
        assert {s.attributes[SESSION] for s in own} == {session}
    assert len({c.context.trace_id for c in claims} | {root.context.trace_id}) == 3


def test_each_model_call_records_what_openrouter_charged(client, spans):
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    work.work_claim("CLM-1001", PricedModel(messages=stub.messages))

    generations = named(spans(), "PricedModel")
    assert len(generations) == 5
    assert {span.attributes[COST] for span in generations} == {'{"total": 4.3e-06}'}


def test_a_model_call_without_a_cost_records_none(client, spans):
    work.work_claim("CLM-1001", script("CLM-1001", "POL-2001", "CUS-3001", "refer", 0))

    assert all(COST not in span.attributes for span in named(spans(), "StubModel"))
