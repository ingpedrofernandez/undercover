"""UnderCover's settings, kept in the database: the approval limit."""

from sqlalchemy import Connection, select

from backend.database import settings


def approval_limit(db: Connection) -> float:
    """Return the largest payout that can be paid without a handler's sign-off."""
    return db.execute(select(settings.c.payout_approval_limit)).scalar_one()


def needs_sign_off(db: Connection, payout: float) -> bool:
    """Say whether a payout is over the approval limit, so it needs a sign-off."""
    return payout > approval_limit(db)
