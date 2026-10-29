import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from agent import __main__ as cli
from agent import harness, work
from agent.tools import CLAIM_TOOLS


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies and keeps the prompts it was sent.

    It raises instead of replying on the calls numbered in fail_at, counting from 0.
    """

    prompts: list[list[BaseMessage]] = []
    fail_at: set[int] = set()

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(messages)
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


def start(client, claim_id, thread_id):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": thread_id})


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
        "record_decision",
        "pay_claim",
    ]
    assert set(names) <= operations


def test_get_instructions(client):
    text = client.get("/api/instructions").json()["claim"]
    assert text.startswith("# UnderCover Agent")
    assert "## 10. How we work out your payment" not in text
    assert "$35 per traveler" not in text


def test_run_approves_and_pays_within_the_limit(client):
    stub = script(
        "CLM-1001",
        "POL-2001",
        "CUS-3001",
        "approve",
        420.0,
        call("pay_claim", text="Paying now.", claim_id="CLM-1001", amount=420.0),
    )
    start(client, "CLM-1001", "thread-1")
    assert work.run_claim_agent("CLM-1001", "thread-1", stub) == "Decision: approve."

    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["thread_id"] == "thread-1"
    assert claim["decision"]["payout"] == 420.0
    assert claim["payment"]["amount"] == 420.0

    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["kind"] for s in steps] == [
        *(["tool_call", "tool_result"] * 4),
        "message",
        "tool_call",
        "tool_result",
        "message",
    ]
    assert steps[0]["content"] == 'get_claim(claim_id="CLM-1001")'
    assert steps[1]["content"].startswith('get_claim: {"claim_id": "CLM-1001"')
    assert steps[8]["content"] == "Paying now."
    assert steps[9]["content"] == 'pay_claim(claim_id="CLM-1001", amount=420.0)'
    assert steps[-1]["content"] == "Decision: approve."
    assert {s["thread_id"] for s in steps} == {"thread-1"}


def test_run_uses_the_instructions_from_the_backend(client):
    stub = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    start(client, "CLM-1003", "thread-1")
    work.run_claim_agent("CLM-1003", "thread-1", stub)
    system = stub.prompts[0][0]
    assert isinstance(system, SystemMessage)
    assert system.content == client.get("/api/instructions").json()["claim"]


def test_payment_over_the_limit_is_refused(client):
    stub = script(
        "CLM-1002",
        "POL-2002",
        "CUS-3002",
        "approve",
        1350.0,
        call("pay_claim", claim_id="CLM-1002", amount=1350.0),
    )
    start(client, "CLM-1002", "thread-2")
    work.run_claim_agent("CLM-1002", "thread-2", stub)

    refusal = stub.prompts[-1][-1]
    assert isinstance(refusal, ToolMessage)
    assert "needs a handler's sign-off" in refusal.text
    assert refusal.text.startswith("Refused: 403: ")
    assert refusal.status == "error"

    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "waiting_for_sign_off"
    assert claim["payment"] is None


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_run_declines_and_refers(client, decision):
    start(client, "CLM-1003", "thread-3")
    work.run_claim_agent(
        "CLM-1003", "thread-3", script("CLM-1003", "POL-2003", "CUS-3003", decision, 0)
    )
    claim = client.get("/api/claims/CLM-1003").json()
    assert claim["status"] == "decided"
    assert claim["decision"]["decision"] == decision
    assert claim["payment"] is None


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
    start(client, "CLM-1020", "thread-5")
    work.run_claim_agent("CLM-1020", "thread-5", stub)

    steps = client.get("/api/claims/CLM-1020/steps").json()
    assert [s["kind"] for s in steps[:3]] == ["tool_call", "tool_result", "tool_call"]
    assert steps[0]["content"] == 'search_documents(query="monkey")'
    assert '"section": 7' in steps[1]["content"]
    assert steps[2]["content"] == 'read_section(document="claims_manual", section=7)'
    assert steps[3]["kind"] == "read"
    title, _, text = steps[3]["content"].partition("\n\n")
    assert title == "Claims manual, section 7: Interpretation notes"
    assert text.startswith("## 7. Interpretation notes")
    assert "**Wild animals.**" in text
    assert steps[4]["content"] == 'list_sections(document="claims_manual")'
    assert '"title": "Repeat claims"' in steps[5]["content"]


def test_a_refused_read_is_an_ordinary_tool_result(client):
    stub = look_up_then_refer(
        call("read_section", document="claims_manual", section=99)
    )
    start(client, "CLM-1020", "thread-6")
    work.run_claim_agent("CLM-1020", "thread-6", stub)

    refusal = stub.prompts[1][-1]
    assert isinstance(refusal, ToolMessage)
    assert refusal.text == "Refused: 404: Section 99 of claims_manual not found"
    steps = client.get("/api/claims/CLM-1020/steps").json()
    assert steps[1]["kind"] == "tool_result"
    assert steps[1]["content"].startswith("read_section: Refused: 404")
    assert "read" not in {s["kind"] for s in steps}


def test_command_line_works_one_claim(monkeypatch, capsys):
    worked = []
    monkeypatch.setattr(
        cli, "work_claim", lambda claim_id: worked.append(claim_id) or "A line."
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
