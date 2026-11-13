"""UnderCover's settings, kept in the database: the approval limit."""

import sqlite3


def approval_limit(db: sqlite3.Connection) -> float:
    """Return the largest payout that can be paid without a handler's sign-off."""
    return db.execute("SELECT payout_approval_limit FROM settings").fetchone()[0]


def needs_sign_off(db: sqlite3.Connection, payout: float) -> bool:
    """Say whether a payout is over the approval limit, so it needs a sign-off."""
    return payout > approval_limit(db)
