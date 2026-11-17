from agent import harness
from agent.tests.test_agent import StubModel, script
from backend.tests.test_runs import create_dispatch

TYPE = "langfuse.observation.type"
SESSION = "session.id"
INPUT = "langfuse.observation.input"
OUTPUT = "langfuse.observation.output"
COST = "langfuse.observation.cost_details"
TAGS = "langfuse.trace.tags"


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
    assert harness.work_claim("CLM-1001", None, stub) == "CLM-1001  decline  $0.00"

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


def test_a_claim_in_a_run_is_tagged_with_the_run(client, spans):
    run_id = create_dispatch(client)
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    harness.work_claim("CLM-1001", run_id, stub)

    traced = spans()
    [root] = named(traced, "work-claim")
    own = in_trace(traced, root)
    [agent] = named(own, "claim-agent")
    assert agent.attributes[TAGS] == (f"run-{run_id}",)
    session = f"CLM-1001:{thread_of(client, 'CLM-1001')}"
    assert {s.attributes[SESSION] for s in own} == {session}


def test_a_claim_with_no_run_has_no_tag(client, spans):
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    harness.work_claim("CLM-1001", None, stub)

    assert all(TAGS not in span.attributes for span in spans())


def test_each_model_call_records_what_openrouter_charged(client, spans):
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "decline", 0)
    harness.work_claim("CLM-1001", None, stub)

    generations = named(spans(), "StubModel")
    assert len(generations) == 5
    assert {span.attributes[COST] for span in generations} == {'{"total": 4.3e-06}'}


def test_the_wait_and_the_payment_are_two_traces_in_one_session(client, spans):
    harness.work_claim(
        "CLM-1002", None, script("CLM-1002", "POL-2002", "CUS-3002", "approve", 1350.0)
    )
    client.post("/api/claims/CLM-1002/sign-off", json={"handler_id": "HND-01"})
    harness.work_claim("CLM-1002", None, StubModel(messages=iter([])))

    traced = spans()
    waited, paid = named(traced, "work-claim")
    assert waited.attributes[OUTPUT] == (
        "CLM-1002  approve  $1,350.00  waiting for sign-off"
    )
    assert paid.attributes[OUTPUT] == "CLM-1002  approve  $1,350.00  paid"
    assert waited.context.trace_id != paid.context.trace_id
    session = f"CLM-1002:{thread_of(client, 'CLM-1002')}"
    assert waited.attributes[SESSION] == paid.attributes[SESSION] == session
    assert named(in_trace(traced, waited), "pay") == []
    assert len(named(in_trace(traced, paid), "pay")) == 1
