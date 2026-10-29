"""The policy wording and the claims manual, section by section."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.database import Database
from backend.models import SearchResult, Section, SectionTitle

router = APIRouter(prefix="/api/documents")


@router.get("/search", operation_id="search_documents")
def search_documents(
    query: Annotated[str, Query(min_length=1)], db: Database
) -> list[SearchResult]:
    """Find the sections of either document with a line containing the query."""
    needle = query.lower()
    results = []
    for row in db.execute("SELECT * FROM sections ORDER BY rowid"):
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


@router.get("/{document}/sections", operation_id="list_sections")
def list_sections(document: str, db: Database) -> list[SectionTitle]:
    """List the sections of the policy wording or the claims manual."""
    rows = db.execute(
        "SELECT document, section, title FROM sections"
        " WHERE document = ? ORDER BY section",
        (document,),
    ).fetchall()
    if not rows:
        raise HTTPException(404, f"Document {document} not found")
    return [SectionTitle(**dict(row)) for row in rows]


@router.get("/{document}/sections/{section}", operation_id="read_section")
def read_section(document: str, section: int, db: Database) -> Section:
    """Read one section of the policy wording or the claims manual."""
    row = db.execute(
        "SELECT * FROM sections WHERE document = ? AND section = ?",
        (document, section),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Section {section} of {document} not found")
    return Section(**dict(row))
