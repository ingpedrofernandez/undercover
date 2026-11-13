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
    handlers,
    metadata,
    policies,
    sections,
    settings,
)

DATA = ROOT / "data"
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


def seed() -> dict[str, int]:
    """Rebuild our tables from data/ and count what they hold.

    On Supabase the undercover schema is made if it's missing, and the
    checkpointer's tables in it are left alone.
    """
    company = load("company.json")
    handler_rows = load("handlers.json")
    customer_rows = load("customers.json")
    policy_rows = load("policies.json")
    claim_rows = load("claims.json")
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
            insert(claims),
            [
                {
                    "claim_id": c["claim_id"],
                    "customer_id": c["customer_id"],
                    "record": json.dumps(c),
                    "status": "waiting",
                }
                for c in claim_rows
            ],
        )
        db.execute(insert(sections), document_sections())
    return {
        "claims": len(claim_rows),
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
        f"Seeded {counts['claims']} claims, {counts['policies']} policies, "
        f"{counts['customers']} customers and {counts['handlers']} handlers "
        f"into {where()}"
    )


if __name__ == "__main__":
    main()
