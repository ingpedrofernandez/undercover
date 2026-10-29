"""Work the queue with the UnderCover Agent: uv run -m agent [--limit N] [CLM-1001]"""

import argparse
import sys
from io import TextIOWrapper
from typing import cast

from agent.main import call_backend, work_claim
from agent.queue import run_queue


def waiting() -> int:
    """Count the claims waiting in the queue."""
    claims = call_backend("GET", "/api/claims")
    return sum(claim["status"] == "waiting" for claim in claims)


def main(args: list[str]) -> None:
    """Work one named claim, or run the queue capped at --limit or all waiting."""
    parser = argparse.ArgumentParser(
        prog="uv run -m agent", description="Work the claims queue."
    )
    parser.add_argument("claim_id", nargs="?", help="work only this claim")
    parser.add_argument("--limit", type=int, help="the most claims the run takes on")
    options = parser.parse_args(args)
    if options.claim_id:
        print(work_claim(options.claim_id))
        return
    limit = options.limit or waiting()
    if limit == 0:
        print("No claims are waiting.")
        return
    print(run_queue(limit))


if __name__ == "__main__":
    # Windows writes piped output in its legacy code page, which can't hold
    # every character a model replies with.
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    main(sys.argv[1:])
