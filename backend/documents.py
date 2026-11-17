"""What the agent reads: its instructions, and the wording and manual by section."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, select

from backend.database import Database, sections
from backend.models import Instructions, SearchResult, Section, SectionTitle

INSTRUCTIONS = Path(__file__).parent / "instructions"

router = APIRouter(prefix="/api")

WORDING_FIRST = case((sections.c.document == "policy_wording", 0), else_=1)


@router.get("/instructions", operation_id="get_instructions")
def get_instructions() -> Instructions:
    """Get the claim agent's instructions for working a claim."""
    return Instructions(claim=(INSTRUCTIONS / "claim.md").read_text(encoding="utf-8"))


@router.get("/documents/search", operation_id="search_documents")
def search_documents(
    query: Annotated[str, Query(min_length=1)], db: Database
) -> list[SearchResult]:
    """Find the sections of either document with a line containing the query."""
    needle = query.lower()
    results = []
    rows = db.execute(
        select(sections).order_by(WORDING_FIRST, sections.c.section)
    ).mappings()
    for row in rows:
        lines = [line for line in row["text"].splitlines() if needle in line.lower()]
        if lines:
            results.append(
                SearchResult(
                    document=row["document"],
                    section=row["section"],
                    title=row["title"],
                    lines=lines,
                )
            )
    return results


@router.get("/documents/{document}/sections", operation_id="list_sections")
def list_sections(document: str, db: Database) -> list[SectionTitle]:
    """List the sections of the policy wording or the claims manual."""
    rows = (
        db.execute(
            select(sections.c.document, sections.c.section, sections.c.title)
            .where(sections.c.document == document)
            .order_by(sections.c.section)
        )
        .mappings()
        .all()
    )
    if not rows:
        raise HTTPException(404, f"Document {document} not found")
    return [SectionTitle(**row) for row in rows]


@router.get("/documents/{document}/sections/{section}", operation_id="read_section")
def read_section(document: str, section: int, db: Database) -> Section:
    """Read one section of the policy wording or the claims manual."""
    row = (
        db.execute(
            select(sections).where(
                sections.c.document == document, sections.c.section == section
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(404, f"Section {section} of {document} not found")
    return Section(**row)
