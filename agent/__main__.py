"""Work the queue with the UnderCover Agent: uv run -m agent [CLM-1001]"""

import sys
import uuid
from io import TextIOWrapper
from typing import cast

from agent.main import run, work_queue


def main(args: list[str]) -> None:
    """Work the claim named on the command line, or every waiting claim."""
    if args:
        print(run(args[0], str(uuid.uuid4())))
    else:
        work_queue()


if __name__ == "__main__":
    # Windows writes piped output in its legacy code page, which can't hold
    # every character a model replies with.
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8")
    main(sys.argv[1:])
