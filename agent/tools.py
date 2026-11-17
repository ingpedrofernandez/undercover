"""Every tool the claim agent uses, named after the backend operations."""

from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent import api

DOCUMENT_NAMES = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}

Document = Literal["policy_wording", "claims_manual"]

Benefit = Literal[
    "trip_cancellation",
    "trip_interruption",
    "trip_delay",
    "baggage_delay",
    "baggage",
    "passport",
    "emergency_medical",
]


class PayoutLine(BaseModel):
    """One covered item or expense on a claim."""

    description: str = Field(description="What the item or expense is")
    amount: float = Field(
        description="The total claimed for the line in US dollars, before any limits."
        " For several items, the total for all of them"
    )
    quantity: int = Field(
        description="How many separate items the line holds, such as 3 for three"
        " shirts, or 1. A pair or a set is one item"
    )
    kind: Literal[
        "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
    ] = Field(
        description="item: a belonging, or a pair or set that counts as one item."
        " electronics: only a phone, tablet, laptop, camera or its lens, e-reader or"
        " smartwatch; any other device is an item. cash: cash that was lost or stolen."
        " expense: any other cost with a receipt, such as a medical bill, a meal, a"
        " taxi, a fee or a prepaid trip cost. hotel: a hotel during a trip delay."
        " meals_without_receipts: meals during a trip delay with no receipts."
    )
    nights: int = Field(description="For a hotel, the number of nights, otherwise 0")
    hours: float = Field(
        description="For meals without receipts, the length of the delay in hours,"
        " otherwise 0"
    )


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


@tool(parse_docstring=True)
def calculate_payout(
    policy_id: str, benefit: Benefit, lines: list[PayoutLine], paid_by_others: float
) -> dict[str, Any]:
    """Work out the payout on an approved claim with UnderCover's payout rules.

    Args:
        policy_id: The customer's policy id
        benefit: The benefit the claim is paid under
        lines: The covered items and expenses, one for each line of the claim, with
            any excluded ones left out
        paid_by_others: What a carrier, hotel or other party has paid or refunded
            for the same loss, or 0
    """
    return api.calculate_payout(
        policy_id, benefit, [line.model_dump() for line in lines], paid_by_others
    )


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


CLAIM_TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    list_sections,
    search_documents,
    read_section,
    calculate_payout,
    record_decision,
]
