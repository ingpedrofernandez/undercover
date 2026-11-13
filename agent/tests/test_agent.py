import json

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from openai.types.chat import ChatCompletion

from agent import __main__ as cli
from agent import harness, work
from agent.tools import CLAIM_TOOLS


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies and keeps the prompts it was sent.

    It raises instead of replying on the calls numbered in fail_at, counting from 0,
    and stops the process, as Ctrl-C would, on the calls numbered in stop_at.
    """

    prompts: list[list[BaseMessage]] = []
    fail_at: set[int] = set()
    stop_at: set[int] = set()

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(messages)
        if len(self.prompts) - 1 in self.stop_at:
            raise KeyboardInterrupt
        if len(self.prompts) - 1 in self.fail_at:
            raise RuntimeError("The model is unavailable")
        return super()._generate(messages, stop, run_manager, **kwargs)


def call(name, text="", **args):
    return AIMessage(
        content=text, tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}]
    )


def decide(claim_id, decision, payout, section="Section 3, Trip Delay"):
    return call(
        "record_decision",
        claim_id=claim_id,
        decision=decision,
        payout=payout,
        section=section,
        reason="The delay was covered.",
    )


def script(claim_id, policy_id, customer_id, decision, payout, *extra):
    return StubModel(
        messages=iter(
            [
                call("get_claim", claim_id=claim_id),
                call("get_policy", policy_id=policy_id),
                call("get_claim_history", customer_id=customer_id),
                decide(claim_id, decision, payout),
                *extra,
                AIMessage(content=f"Decision: {decision}."),
            ]
        )
    )


def claim(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def steps(client, claim_id):
    return client.get(f"/api/claims/{claim_id}/steps").json()


def test_tools_are_named_after_backend_operations(client):
    operations = {
        operation["operationId"]
        for path in client.get("/openapi.json").json()["paths"].values()
        for operation in path.values()
    }
    names = [t.name for t in CLAIM_TOOLS]
    assert names == [
        "get_claim",
        "get_policy",
        "get_claim_history",
        "list_sections",
        "search_documents",
        "read_section",
        "calculate_payout",
        "record_decision",
    ]
    assert set(names) <= operations


def test_the_claim_graph_has_the_nodes_and_edges_of_the_design():
    graph = harness.claim_graph(StubModel(messages=iter([]))).get_graph()
    assert set(graph.nodes) == {
        "__start__",
        "agent",
        "tools",
        "sign_off",
        "pay",
        "__end__",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", "agent"),
        ("agent", "tools"),
        ("agent", "sign_off"),
        ("agent", "pay"),
        ("agent", "__end__"),
        ("tools", "agent"),
        ("sign_off", "pay"),
        ("pay", "__end__"),
    }


def test_get_instructions(client):
    text = client.get("/api/instructions").json()["claim"]
    assert text.startswith("# UnderCover Agent")
    assert "## 10. How we work out your payment" not in text
    assert "$35 per traveler" not in text


def test_an_approval_within_the_limit_is_paid_by_the_graph(client):
    stub = script("CLM-1001", "POL-2001", "CUS-3001", "approve", 420.0)
    assert work.work_claim("CLM-1001", stub) == "CLM-1001  approve  $420.00  paid"

    found = claim(client, "CLM-1001")
    assert found["status"] == "decided"
    assert found["decision"]["payout"] == 420.0
    assert found["payment"]["amount"] == 420.0
    assert found["payment"]["signed_off_by"] is None

    recorded = steps(client, "CLM-1001")
    assert [s["kind"] for s in recorded] == [
        *(["tool_call", "tool_result"] * 4),
        "message",
        "tool_call",
        "tool_result",
    ]
    assert recorded[0]["content"] == 'get_claim(claim_id="CLM-1001")'
    assert recorded[1]["content"].startswith('get_claim: {"claim_id": "CLM-1001"')
    assert recorded[8]["content"] == "Decision: approve."
    assert recorded[9]["content"] == 'pay_claim(claim_id="CLM-1001", amount=420.0)'
    assert recorded[10]["content"].startswith('pay_claim: {"claim_id": "CLM-1001"')
    assert {s["thread_id"] for s in recorded} == {found["thread_id"]}


SUITCASE = {
    "description": "Hard-shell suitcase",
    "amount": 239.99,
    "quantity": 1,
    "kind": "item",
    "nights": 0,
    "hours": 0,
}


def test_the_payout_comes_from_the_payout_rules(client):
    stub = StubModel(
        messages=iter(
            [
                call(
                    "calculate_payout",
                    policy_id="POL-2007",
                    benefit="baggage",
                    lines=[SUITCASE],
                    paid_by_others=0,
                ),
                decide("CLM-1007", "approve", 50.0),
                AIMessage(content="Decision: approve."),
            ]
        )
    )
    work.work_claim("CLM-1007", stub)

    worked_out = json.loads(stub.prompts[1][-1].text)
    assert worked_out["payout"] == 50.0
    assert worked_out["needs_sign_off"] is False
    assert claim(client, "CLM-1007")["decision"]["payout"] == 50.0
    recorded = steps(client, "CLM-1007")
    assert recorded[0]["content"] == (
        'calculate_payout(policy_id="POL-2007", benefit="baggage",'
        f" lines={json.dumps([SUITCASE])}, paid_by_others=0)"
    )
    assert recorded[1]["content"].startswith("calculate_payout: {")
    assert "Hard-shell suitcase, limited to $150.00" in recorded[1]["content"]
    assert "Less the deductible" in recorded[1]["content"]


def test_the_claim_agent_gets_the_instructions_from_the_backend(client):
    stub = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    work.work_claim("CLM-1003", stub)
    system = stub.prompts[0][0]
    assert isinstance(system, SystemMessage)
    assert system.content == client.get("/api/instructions").json()["claim"]


def test_an_approval_over_the_limit_waits_for_a_sign_off(client):
    stub = script("CLM-1002", "POL-2002", "CUS-3002", "approve", 1350.0)
    line = work.work_claim("CLM-1002", stub)
    assert line == "CLM-1002  approve  $1,350.00  waiting for sign-off"

    found = claim(client, "CLM-1002")
    assert found["status"] == "waiting_for_sign_off"
    assert found["payment"] is None
    graph = harness.claim_graph(StubModel(messages=iter([])))
    saved = graph.get_state(harness.thread(found["thread_id"]))
    assert saved.next == ("sign_off",)
    assert saved.interrupts[0].value == {"claim_id": "CLM-1002", "payout": 1350.0}
    assert "pay_claim" not in {
        s["content"].split("(")[0] for s in steps(client, "CLM-1002")
    }


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_declines_and_referrals_are_decided_and_unpaid(client, decision):
    work.work_claim("CLM-1003", script("CLM-1003", "POL-2003", "CUS-3003", decision, 0))
    found = claim(client, "CLM-1003")
    assert found["status"] == "decided"
    assert found["decision"]["decision"] == decision
    assert found["payment"] is None


def look_up_then_refer(*lookups):
    return StubModel(
        messages=iter(
            [
                *lookups,
                decide(
                    "CLM-1020",
                    "refer",
                    0,
                    section="Claims manual, section 7, Interpretation notes",
                ),
                AIMessage(content="Decision: refer."),
            ]
        )
    )


def test_reading_a_section_is_recorded_as_a_read(client):
    stub = look_up_then_refer(
        call("search_documents", query="monkey"),
        call("read_section", document="claims_manual", section=7),
        call("list_sections", document="claims_manual"),
    )
    work.work_claim("CLM-1020", stub)

    recorded = steps(client, "CLM-1020")
    assert [s["kind"] for s in recorded[:3]] == [
        "tool_call",
        "tool_result",
        "tool_call",
    ]
    assert recorded[0]["content"] == 'search_documents(query="monkey")'
    assert '"section": 7' in recorded[1]["content"]
    assert recorded[2]["content"] == (
        'read_section(document="claims_manual", section=7)'
    )
    assert recorded[3]["kind"] == "read"
    title, _, text = recorded[3]["content"].partition("\n\n")
    assert title == "Claims manual, section 7: Interpretation notes"
    assert text.startswith("## 7. Interpretation notes")
    assert "**Wild animals.**" in text
    assert recorded[4]["content"] == 'list_sections(document="claims_manual")'
    assert '"title": "Repeat claims"' in recorded[5]["content"]


def test_a_refusal_reaches_the_model_and_is_a_tool_result(client):
    stub = look_up_then_refer(
        call("read_section", document="claims_manual", section=99)
    )
    work.work_claim("CLM-1020", stub)

    refusal = stub.prompts[1][-1]
    assert isinstance(refusal, ToolMessage)
    assert refusal.text == "Refused: 404: Section 99 of claims_manual not found"
    assert refusal.status == "error"
    recorded = steps(client, "CLM-1020")
    assert recorded[1]["kind"] == "tool_result"
    assert recorded[1]["content"].startswith("read_section: Refused: 404")
    assert "read" not in {s["kind"] for s in recorded}


def test_a_call_with_the_wrong_arguments_reaches_the_model(client):
    stub = look_up_then_refer(call("read_section", document="claims_manual"))
    work.work_claim("CLM-1020", stub)

    error = stub.prompts[1][-1]
    assert isinstance(error, ToolMessage)
    assert error.status == "error"
    assert "section" in error.text
    assert claim(client, "CLM-1020")["status"] == "decided"


def test_command_line_works_one_claim(monkeypatch, capsys):
    worked = []
    monkeypatch.setattr(
        cli, "work_one_claim", lambda claim_id: worked.append(claim_id) or "A line."
    )
    cli.main(["CLM-1001"])
    assert capsys.readouterr().out == "A line.\n"
    assert worked == ["CLM-1001"]


def test_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert harness.model().model_name == "deepseek/deepseek-v4.1-flash"
    assert harness.model().reasoning_effort == "low"
    assert harness.model().request_timeout == 120
    assert harness.model().max_retries == 0
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert harness.model().model_name == "openrouter/free"
    assert harness.model().reasoning_effort is None


def test_model_keeps_the_reasoning_openrouter_sends(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    reply = ChatCompletion.model_validate(
        {
            "id": "reply-1",
            "object": "chat.completion",
            "created": 0,
            "model": "deepseek/deepseek-v4.1-flash",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "Approve.",
                        "reasoning": "The delay was over six hours.",
                    },
                }
            ],
        }
    )
    message = harness.model()._create_chat_result(reply).generations[0].message
    assert message.additional_kwargs["reasoning_content"] == (
        "The delay was over six hours."
    )
