"""Work the queue with the UnderCover Agent: uv run -m agent [--limit N] [CLM-1001]"""

import argparse
import sys
from io import TextIOWrapper
from typing import cast

from agent import api
from agent.work import run_queue, work_one_claim


def main(args: list[str]) -> None:
    """Work one named claim, or run the queue capped at --limit or all waiting."""
    parser = argparse.ArgumentParser(
        prog="uv run -m agent", description="Work the claims queue."
    )
    parser.add_argument("claim_id", nargs="?", help="work only this claim")
    parser.add_argument("--limit", type=int, help="the most claims the run takes on")
    options = parser.parse_args(args)
    if options.claim_id:
        try:
            print(work_one_claim(options.claim_id))
        except api.ApiError as error:
            print(f"{options.claim_id}  not started: {error}")
        return
    waiting = sum(claim["status"] == "waiting" for claim in api.list_claims())
    limit = options.limit or waiting
    if limit == 0:
        print("No claims are waiting.")
        return
    print(run_queue(limit))


if __name__ == "__main__":
    # Windows writes piped output in its legacy code page, which can't hold
    # every character a model replies with.
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    main(sys.argv[1:])
