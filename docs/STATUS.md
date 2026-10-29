# Status

The claims pilot in `docs/PLAN.md` is built: all six phases are done.

The harness in `docs/PLAN_HARNESS.md` is being built: phases 1 to 4 of 6 are done.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173.
- `uv run -m backend.seed` rebuilds the database from `data/`, putting every claim back in the queue.
- `uv run -m agent` works every waiting claim in queue order and prints a line for each, then a count. `uv run -m agent CLM-1001` works one claim and prints its line. Both use the real model through OpenRouter: DeepSeek V4.1 Flash, or the model in `MODEL_NAME`.

## Built

- `backend/`: SQLite database seeded from `data/` (never `data/evals/`), at `undercover.db` or the path in `UNDERCOVER_DB`, created on startup when missing. Read operations: `health`, `list_claims`, `get_claim`, `get_policy`, `get_claim_history`, `list_handlers`, `list_steps`, `get_instructions`. The policy wording and the claims manual are stored section by section, read with `list_sections`, `search_documents` and `read_section` in `backend/documents.py`. Runs of the agent over the queue are kept in `backend/runs.py`: `start_run` (capped at a number of claims), `write_todos`, `finish_run` with a summary, and `get_latest_run`, which returns null before the first run. Workflow operations: `start_claim`, `record_step`, `record_decision`, `pay_claim`, `sign_off_claim`, `record_failure`. A claim moves from waiting to in progress to decided, or to waiting for sign-off when an approval pays over the limit in `company.json`. `record_failure` puts a claim in progress back in the queue with an `error` step, and a second failure moves it to left for a handler. `pay_claim` refuses such a payout with a 403 until a handler signs off, and signing off pays it. The agent's instructions for working a claim are in `backend/instructions/claim.md`, written from the policy wording and the claims manual, and `get_instructions` serves them as `claim`, without either document. A test checks that every operation follows the API rules.
- `agent/`: `work_claim(claim_id)` starts a claim, runs the claim agent, records a failure if it raises or ends without a decision, and returns a one-line report built from the backend's record. `run(claim_id, thread_id)` is the claim agent: it fetches its instructions from the backend and works a started claim with eight tools named after backend operations: `get_claim`, `get_policy`, `get_claim_history`, `list_sections`, `search_documents`, `read_section`, `record_decision` and `pay_claim`. It records every tool call, tool result and message as a step, and each section it reads as a `read` step whose first line names the section. The model has a 120-second timeout, `ModelRetryMiddleware` retries a failed call twice, and `ModelCallLimitMiddleware` stops a claim at 30 model calls. `work_queue()` runs `work_claim` on each waiting claim.
- `dashboard/`: the queue (`/`), with counts by state, including left for a handler, the agent's to-do list for the latest run with its summary, and a line per claim. A claim in full (`/claims/:claimId`), with its policy, earlier claims, the decision and payment, the sections the agent read, the agent's steps as it works, and a sign-off form for a held payout. The agent's instructions (`/instructions`), read only. The queue and a claim page refresh every two seconds. Styled to `BRAND.md` in light and dark mode.
- `e2e/`: tests of the three pages, the agent's steps and the sections it read appearing on a claim page, a claim failing twice, the to-do list filling in on the queue page, and a handler signing off a held payout. Playwright runs its own backend on port 8001 with `e2e/undercover.db`, and its own dashboard on port 5174, so it can run next to `npm run dev`.

## Last live run

On September 27, 2026, `uv run -m agent` with `openai/gpt-6-luna` worked all 25 claims in 2 minutes 47 seconds: 17 approve, 5 decline and 3 refer. Three approvals were over $1,000 and waited for sign-off (CLM-1003, CLM-1008 and CLM-1011), and every other approval was paid its payout. These decisions have not yet been scored against the handlers' decisions in `data/evals/`.
