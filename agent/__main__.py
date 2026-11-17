"""Work one claim with the UnderCover Agent: uv run -m agent CLM-1001

A claim in progress carries on from where it stopped, and a waiting claim is
started. Dispatches are started from the dashboard.
"""

import argparse
import sys
from io import TextIOWrapper
from typing import cast

from dotenv import load_dotenv

from agent import api, harness


def main(args: list[str]) -> None:
    """Work the claim named on the command line and print its line."""
    parser = argparse.ArgumentParser(
        prog="uv run -m agent", description="Work one claim."
    )
    parser.add_argument("claim_id", help="the claim to work")
    options = parser.parse_args(args)
    try:
        print(harness.work_claim(options.claim_id, None))
    except api.ApiError as error:
        print(f"{options.claim_id}  not started: {error}")


if __name__ == "__main__":
    load_dotenv(override=True)
    # Windows writes piped output in its legacy code page, which can't hold
    # every character a model replies with.
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    main(sys.argv[1:])
