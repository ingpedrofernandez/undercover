"""Rebuild the database from data/, with: uv run -m backend.seed"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.database import ROOT, SCHEMA, database_path

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


def seed(path: Path) -> dict[str, int]:
    """Build a fresh database at path from data/ and count what it holds."""
    company = load("company.json")
    handlers = load("handlers.json")
    customers = load("customers.json")
    policies = load("policies.json")
    claims = load("claims.json")
    path.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO settings VALUES (?)", (company["payout_approval_limit"],)
        )
        connection.executemany(
            "INSERT INTO handlers VALUES (?, ?, ?, ?)",
            [
                (h["handler_id"], h["name"], h["role"], h["can_approve_over_limit"])
                for h in handlers
            ],
        )
        connection.executemany(
            "INSERT INTO customers VALUES (?, ?, ?)",
            [(c["customer_id"], c["name"], json.dumps(c)) for c in customers],
        )
        connection.executemany(
            "INSERT INTO policies VALUES (?, ?)",
            [(p["policy_id"], json.dumps(p)) for p in policies],
        )
        connection.executemany(
            "INSERT INTO claims (claim_id, customer_id, record, status)"
            " VALUES (?, ?, ?, 'waiting')",
            [(c["claim_id"], c["customer_id"], json.dumps(c)) for c in claims],
        )
        for document, name in DOCUMENTS.items():
            text = (DATA / name).read_text(encoding="utf-8")
            connection.executemany(
                "INSERT INTO sections VALUES (?, ?, ?, ?)",
                [(document, *section) for section in split_sections(text)],
            )
    return {
        "claims": len(claims),
        "policies": len(policies),
        "customers": len(customers),
        "handlers": len(handlers),
    }


def main() -> None:
    """Rebuild the database and say what it holds."""
    path = database_path()
    counts = seed(path)
    print(
        f"Seeded {counts['claims']} claims, {counts['policies']} policies, "
        f"{counts['customers']} customers and {counts['handlers']} handlers "
        f"into {path.name}"
    )


if __name__ == "__main__":
    main()
