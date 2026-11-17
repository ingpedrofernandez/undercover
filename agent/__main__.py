"""Work the queue with the UnderCover Agent: uv run -m agent [--limit N] [CLM-1001]

A run first finishes a run that was stopped and carries on every claim in progress.
"""

import argparse
import sys
from io import TextIOWrapper
from typing import cast

from dotenv import load_dotenv

from agent import api, harness
from agent.work import catch_up, run_queue


def main(args: list[str]) -> None:
    """Work one claim, or catch up and run the queue capped at --limit or waiting."""
    parser = argparse.ArgumentParser(
        prog="uv run -m agent", description="Work the claims queue."
    )
    parser.add_argument("claim_id", nargs="?", help="work only this claim")
    parser.add_argument("--limit", type=int, help="the most claims the run takes on")
    options = parser.parse_args(args)
    if options.claim_id:
        try:
            print(harness.work_claim(options.claim_id, None))
        except api.ApiError as error:
            print(f"{options.claim_id}  not started: {error}")
        return
    catch_up()
    waiting = sum(claim["status"] == "waiting" for claim in api.list_claims())
    limit = options.limit or waiting
    if limit == 0:
        print("No claims are waiting.")
        return
    print(run_queue(limit))


if __name__ == "__main__":
    load_dotenv(override=True)
    # Windows writes piped output in its legacy code page, which can't hold
    # every character a model replies with.
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    main(sys.argv[1:])
