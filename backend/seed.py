"""Rebuild the database from data/, with: uv run -m backend.seed"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import insert
from sqlalchemy.schema import CreateSchema

from backend.database import (
    ROOT,
    SCHEMA,
    claims,
    customers,
    engine,
    handler_decisions,
    handlers,
    held_out_claims,
    metadata,
    policies,
    sections,
    settings,
)

DATA = ROOT / "data"
ANSWER_KEY = {
    "evaluation": "evals/decisions.json",
    "held_out": "evals/held_out_decisions.json",
}
DOCUMENTS = {"policy_wording": "policy_wording.md", "claims_manual": "claims_manual.md"}


def load(name: str) -> Any:
    """Read one of the JSON files in data/."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def split_sections(text: str) -> list[tuple[int, str, str]]:
    """Split a document into numbered sections; the lines before section 1 are 0."""
    intro, *parts = text.split("\n## ")
    found = [(0, intro.splitlines()[0].removeprefix("# "), intro.strip())]
    for part in parts:
        number, _, title = part.splitlines()[0].partition(". ")
        found.append((int(number), title, f"## {part.strip()}"))
    return found


def document_sections() -> list[dict[str, Any]]:
    """Return the sections of the policy wording and the claims manual as rows."""
    return [
        {"document": document, "section": number, "title": title, "text": text}
        for document, name in DOCUMENTS.items()
        for number, title, text in split_sections(
            (DATA / name).read_text(encoding="utf-8")
        )
    ]


def answer_key() -> list[dict[str, Any]]:
    """Return the handlers' decisions on both labelled sets, as rows."""
    return [
        {
            "eval_set": eval_set,
            "claim_id": d["claim_id"],
            "decision": d["decision"],
            "payout": d["payout"],
            "tiny": d["tiny"],
        }
        for eval_set, name in ANSWER_KEY.items()
        for d in load(name)
    ]


def claim_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return claims as rows, each with its record as JSON."""
    return [
        {
            "claim_id": c["claim_id"],
            "customer_id": c["customer_id"],
            "record": json.dumps(c),
        }
        for c in rows
    ]


def seed() -> dict[str, int]:
    """Rebuild our tables from data/ and count what they hold.

    The held-out claims and the handlers' decisions on both labelled sets, from
    data/evals/, go in tables of their own, out of the queue. On Supabase the
    undercover schema is made if it's missing, and the checkpointer's tables in
    it are left alone.
    """
    company = load("company.json")
    handler_rows = load("handlers.json")
    customer_rows = load("customers.json")
    policy_rows = load("policies.json")
    queue = load("claims.json")
    held_out = load("evals/held_out_claims.json")
    database = engine()
    with database.begin() as db:
        if database.dialect.name == "postgresql":
            db.execute(CreateSchema(SCHEMA, if_not_exists=True))
        metadata.drop_all(db)
        metadata.create_all(db)
        db.execute(
            insert(settings),
            [{"payout_approval_limit": company["payout_approval_limit"]}],
        )
        db.execute(
            insert(handlers),
            [
                {column.name: h[column.name] for column in handlers.c}
                for h in handler_rows
            ],
        )
        db.execute(
            insert(customers),
            [
                {
                    "customer_id": c["customer_id"],
                    "name": c["name"],
                    "record": json.dumps(c),
                }
                for c in customer_rows
            ],
        )
        db.execute(
            insert(policies),
            [
                {"policy_id": p["policy_id"], "record": json.dumps(p)}
                for p in policy_rows
            ],
        )
        db.execute(
            insert(claims), [row | {"status": "waiting"} for row in claim_rows(queue)]
        )
        db.execute(insert(held_out_claims), claim_rows(held_out))
        db.execute(insert(handler_decisions), answer_key())
        db.execute(insert(sections), document_sections())
    return {
        "claims": len(queue),
        "held_out": len(held_out),
        "policies": len(policy_rows),
        "customers": len(customer_rows),
        "handlers": len(handler_rows),
    }


def where() -> str:
    """Name the database being seeded: SQLite's file, or the schema and its host."""
    url = engine().url
    if url.drivername == "sqlite":
        return Path(str(url.database)).name
    return f"the {SCHEMA} schema on {url.host}"


def main() -> None:
    """Rebuild the database and say what it holds."""
    counts = seed()
    print(
        f"Seeded {counts['claims']} claims, {counts['held_out']} held-out claims, "
        f"{counts['policies']} policies, {counts['customers']} customers and "
        f"{counts['handlers']} handlers into {where()}"
    )


if __name__ == "__main__":
    main()
