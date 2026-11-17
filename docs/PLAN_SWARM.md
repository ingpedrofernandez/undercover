# Plan: a swarm of claim agents and a scoreboard

This plan builds the brief in `SWARM.md` on top of durable state, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

When it's done, a dispatcher with no model takes the queue agent's place. A handler starts a dispatch on the queue page with N claim agents at once, from 1 to 25. The dispatch carries on every claim left in progress and works every waiting claim, oldest submitted first, each on its own thread as today. A rate limit or a timeout makes a claim wait and carry on as the same attempt. Any other error sends the claim back to the queue, and the same dispatch tries it once more. Every model call's tokens and cost, and the time spent on each claim, are recorded with the dispatch or evaluation they happened in. On a new Scoreboard page a handler runs evaluations on copies of the labelled claims, through the same dispatcher, and the backend scores them from its own records. Each claim's trace in Langfuse is tagged with its run. The agent runs on GPT-6 Luna by default.

> **Sidenote from the brief:** For consistency with the course, please read `labs/week2day4.ipynb` and build the dispatcher in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

## Design

### Following the lab

The dispatcher is built the way `labs/week2day4.ipynb` builds it, and differs only where the brief or the product asks for something else.

| As in the lab | Different, and why |
| --- | --- |
| A `StateGraph` with no model: a `list_claims` node, and a conditional edge `fan_out` that returns one `Send("work_claim", ...)` per claim | `list_claims` asks the backend for the claims (`take_claims`), which also records them on the run, in place of a dict loaded from a file |
| `max_concurrency` in the config caps the claim agents working at once | N comes from the handler, from 1 to 25 |
| `results` with `operator.add`, so the workers' returns add up | The state only collects each claim's line for the console. The backend's records are what counts: the run panel, the summary and the scores are all built from them |
| A `RetryPolicy` on the worker | `retry_on` is only `ModelRateLimitError` and `ModelTimeoutError`, as the brief says. An `error_handler` leaves the claim in progress when the retries run out, so nothing stops the dispatch. Any other error fails the claim as today, and a second round, `list_retries` and `retry_claim`, tries it once more in the same dispatch |
| The worker runs the claim agent with `invoke` and reads what it recorded | The worker calls one harness function, `harness.work_claim(claim_id, run_id)`. Each claim keeps its own thread and checkpoints, never one thread for the dispatch, because a claim can wait days for a sign-off (the lab's own note says so) |
| The cost of a claim is the sum of `response_metadata["token_usage"]["cost"]` | The claim graph's `agent` node records each call's tokens and cost through the backend, with the run |
| `is_right`, `mistake_cost` and `run_scores`, with `WRONGFUL_DECLINE = 1500` and `NEEDLESS_REFERRAL = 50`, and a claim with nothing recorded counted as a referral | The same rules in `backend/scoring.py`, from the backend's records. A claim's time leaves out any wait for a sign-off |
| GPT-6 Luna through OpenRouter with `reasoning_effort="low"` and a 120-second timeout | Through `ChatDeepSeek` as today, which keeps the reasoning OpenRouter sends, with `max_retries=0`, since the graph's retry policies do the retrying |
| Langfuse's `CallbackHandler`, one trace for the whole run named with `run_name` | Each claim stays a trace of its own in its session, tagged with its run's id through `langfuse_tags` in the metadata, so a whole run can be found together |

The lab's challenges (a `score_run` node, a checkpointed dispatcher) are not built: the backend scores, and the dispatcher saves nothing of its own.

### The dispatcher

```mermaid
flowchart LR
    START --> list_claims
    list_claims -. one Send per claim .-> work_claim
    work_claim --> list_retries
    list_retries -. one Send per claim back in the queue .-> retry_claim
    retry_claim --> END
```

**State.** `run_id`, `skip` (claims the service is resuming), `claims` (the claims taken in the first round) and `lines`, with `operator.add`. A `Send` carries `{claim_id, run_id}`.

**Nodes.**

| Node | What it does |
| --- | --- |
| `list_claims` | `api.take_claims(run_id, skip)`: the backend picks the run's claims and records them on the run |
| `work_claim` | Calls `harness.work_claim(claim_id, run_id)`, prints the claim's line and returns it. A `RetryPolicy` with `retry_on=(ModelRateLimitError, ModelTimeoutError)` and a few waits that grow, and an `error_handler` that returns a line saying the claim stays in progress for the next dispatch |
| `list_retries` | Runs once, after every first-round claim is done. Picks the first-round claims back in the queue (`get_claim` says `waiting`): each of them failed once in this dispatch |
| `retry_claim` | The same function, retry policy and error handler as `work_claim` |

`dispatcher.run(run_id, agents, skip)` invokes the graph with `max_concurrency=agents` and no checkpointer, and returns the claims it took. A conditional edge that returns no `Send` ends the graph, so an empty queue or a dispatch with nothing to retry finishes at once.

**The one function.** `harness.work_claim(claim_id, run_id)` carries on a claim in progress or starts a waiting one, as `work.work_one_claim` does today, and returns its line. It is the only place the dispatcher touches the claim agent. It records the time it worked, whatever happens. It settles the claim as today (a decision, or `record_failure` back to the queue) except for `ModelRateLimitError` and `ModelTimeoutError`, which it lets through unsettled, so the worker's retry carries the claim on from its last saved step as the same attempt. The `agent` node's own `RetryPolicy` stays as it is, so a rate limit reaches the worker only after the node's two quick retries.

### Who guarantees what

| Rule from the brief | Enforced by |
| --- | --- |
| Never more than N claims at once | `max_concurrency=N` on the dispatcher's invoke |
| Code chooses the claims, oldest submitted first | The backend's `take_claims`: for a dispatch, the queue's claims in progress and waiting; for an evaluation, its copies. Ordered by `submitted_on`, then id |
| A rate limit or timeout carries on as the same attempt | `harness.work_claim` lets those errors through without `record_failure`; the worker's `RetryPolicy` calls it again, which carries the claim's own thread on |
| Still hitting them after the waits, the claim stays in progress | The worker's `error_handler` returns a line and leaves the claim alone; the next dispatch takes it as in progress |
| Any other error: back to the queue, tried once more in the same dispatch, left for a handler after two | `record_failure`, as today; `list_retries` and `retry_claim` |
| One bad claim never stops the dispatch | The `error_handler` catches whatever the worker raises after its retries |
| Nothing decided or paid twice | The backend, as today |
| One dispatch or evaluation at a time | The service's run lock, taken without waiting: a second start gets a 409 |
| A dispatch skips a claim the service is resuming | The service keeps the claims it's resuming and passes them as `skip` |
| A run killed partway shows as stopped | The service marks every running run stopped when it starts |
| Copies never in the queue, never in a dispatch, never signed off | `list_claims` and a dispatch's `take_claims` leave out claims with an `evaluation_id`; `sign_off_claim` refuses a copy with a 409 |
| The agent never sees the handlers' decisions | They're only in `handler_decisions`, which only seeding and the evaluations router touch. The agent's service never calls `get_evaluation` |
| Each claim run has a saver of its own | `harness.checkpointer()` builds a new `PostgresSaver` on the process's one pool for every claim graph |
| At most 4 connections in each process, waiting rather than failing | The backend's pool and slots, as today; the agent's `ConnectionPool` of at most 4 with a `timeout` long enough that a claim waits for a connection instead of failing after psycopg_pool's default 30 seconds |

### Runs and their records

A run is a dispatch or an evaluation, in one `runs` table, so cost and time point at one kind of row and "one at a time" is about one table.

| Table | Columns | Notes |
| --- | --- | --- |
| `runs` | `run_id`, `kind` (`dispatch` or `evaluation`), `agents`, `model`, `reasoning_effort` (`low` or `none`), `eval_set` and `tiny` (evaluations only), `status` (`running`, `finished`, `stopped`), `started_at`, `finished_at` | Replaces the old runs table: `claim_limit`, `summary` and `todos` go |
| `run_claims` | `run_id`, `claim_id` | The claims a run took, written by `take_claims` |
| `model_calls` | `call_id`, `claim_id`, `run_id` (null with no run), `input_tokens`, `output_tokens`, `cost`, `created_at` | OpenRouter's `prompt_tokens`, `completion_tokens` and `cost` for each reply |
| `work_times` | `work_id`, `claim_id`, `run_id` (null with no run), `started_at`, `seconds` | One row per piece of work on a claim: starting it, carrying it on, or paying it after a sign-off. The graph stops at a sign-off, so the wait is never inside a piece |
| `held_out_claims` | `claim_id`, `customer_id`, `record` | The held-out set, out of the queue |
| `handler_decisions` | `eval_set`, `claim_id`, `decision`, `payout`, `tiny` | The answer key for both sets, from `data/evals/` |
| `claims` | gains `evaluation_id` and `source_id` | Null for the queue. A copy's id is `<source id>-<run id>`, such as `CLM-1008-7`, written into its `record` too |

A claim's time in a run is the sum of its `work_times` in that run, and its cost the sum of its `model_calls`, failed attempts included. A piece of work killed with its process records no time.

The resume after a sign-off has no run, so its time and its model calls (none, since `pay` calls no model) are recorded with no run.

### Evaluations

`create_evaluation` records the run with its set, N, model and effort, and copies the set's claims (all 25, or the five `tiny` ones) into `claims`: the queue's original records for the evaluation set, `held_out_claims` for the held-out set. Each copy is waiting, with a new id, its `evaluation_id` and its `source_id`. `get_claim` on a copy shows its `evaluation_id`, so its page can leave out the sign-off form, and nothing from `handler_decisions`.

`work.evaluate` creates the evaluation, runs the dispatcher on it, clears every copy's saved progress through `harness.clear_progress` (the checkpointer's `delete_thread`), and finishes the run. A copy held for sign-off stays held and counts as finished: it isn't in progress or waiting, so nothing takes it again.

**Scoring**, in `backend/scoring.py`, from the copy's decision (or a referral with payout 0 when it has none) against `handler_decisions`:

| Measure | For the run |
| --- | --- |
| `decision_accuracy` | Share of claims whose decision matches the handler's |
| `accuracy` | Share whose decision matches and payout is within a dollar |
| `cost_of_mistakes` | Sum over claims: a wrongful decline $1,500, a wrongful approval its payout (paid or not), a needless referral $50, a right approval with the wrong amount the difference |
| `straight_through` | Share of claims not referred |
| `cost_per_claim` | The run's model cost divided by its claims |
| `seconds_per_claim` | The mean of its claims' times |
| `run_seconds` | `finished_at` less `started_at`; none for a run that stopped or is running |

### The agent's service

| Operation | Route | What it does |
| --- | --- | --- |
| `start_dispatch` | `POST /api/dispatches` | Body `{agents}`. 409 if a run is going, otherwise 202 at once, then `work.dispatch` in the background |
| `start_evaluation` | `POST /api/evaluations` | Body `{agents, eval_set, tiny}`. The same, with `work.evaluate` |
| `resume_claim` | `POST /api/claims/{claim_id}/resume` | As today, and the claim is in `RESUMING` until it's done |
| `health` | `GET /api/health` | As today |

On startup it opens the pool and calls `api.stop_runs()`. `npm run dev` starts the backend and the service together, so the agent's backend client retries connecting for a few seconds (httpx's `HTTPTransport(retries=...)`), and the service's startup doesn't fail when it comes up first.

### API

Every operation keeps an `operation_id`, a one-line docstring and no optional inputs: a run id that can be null is a required field.

| Operation | Route | Called by | What it does |
| --- | --- | --- | --- |
| `record_model_call` | `POST /api/claims/{claim_id}/model-calls` | the `agent` node | `{run_id, input_tokens, output_tokens, cost}` |
| `record_work_time` | `POST /api/claims/{claim_id}/work-times` | `harness.work_claim` | `{run_id, started_at, seconds}` |
| `start_dispatch` | `POST /api/dispatches/start` | the dashboard | `{agents}`, 1 to 25. Asks the service and writes nothing. 202, the service's 409, or 503 "The agent's service isn't running" |
| `create_dispatch` | `POST /api/dispatches` | the service | `{agents, model, reasoning_effort}`. Returns the running dispatch |
| `get_latest_dispatch` | `GET /api/dispatches/latest` | the run panel | The newest dispatch, or null: its claims (status, decision, payout, first start in the run, time, cost), its model cost, its run time and the claims' time, and once it isn't running, its summary |
| `take_claims` | `POST /api/runs/{run_id}/claims` | the dispatcher | `{skip}`. Picks and records the run's claims, and returns their ids. 409 for a run that isn't running |
| `finish_run` | `POST /api/runs/{run_id}/finish` | the work | Finishes a running run. 409 otherwise |
| `stop_runs` | `POST /api/runs/stop` | the service, on startup | Marks every running run stopped |
| `start_evaluation` | `POST /api/evaluations/start` | the dashboard | `{agents, eval_set, tiny}`, as `start_dispatch` |
| `create_evaluation` | `POST /api/evaluations` | the service | `{agents, eval_set, tiny, model, reasoning_effort}`. Makes the copies |
| `list_evaluations` | `GET /api/evaluations` | the scoreboard | Every evaluation, newest first, with its measures |
| `get_evaluation` | `GET /api/evaluations/{run_id}` | the evaluation page | Its measures and each copy: the handler's decision and payout beside the agent's, the agent's reason, cost and time, and whether it's a miss |
| `sign_off_claim` | | | 409 for a copy |
| `list_claims` | | | Leaves out copies |
| `get_claim` | | | Gains `evaluation_id` |
| `get_instructions` | | | Returns only `claim` |
| `start_run`, `write_todos`, `get_latest_run` | | | Go |

The summary is data, not prose: the counts approved, declined and referred, each payout waiting for a sign-off with its claim, the claims left for a handler and the claims still in progress. The dashboard words it.

### Modules

The agent's modules depend on each other in one direction: `api` ← `tools` ← `harness` ← `dispatcher` ← `work` ← `service`, and `__main__` uses `harness`.

| Module | | Its one job | Imports |
| --- | --- | --- | --- |
| `agent/api.py` | changed | Every call to the backend; adds the run, cost and time operations, drops the queue agent's; retries connecting | `httpx` |
| `agent/tools.py` | changed | The claim agent's tools only: the queue agent's, `RunContext` and `Todo` go | `api` |
| `agent/harness.py` | changed | The model (GPT-6 Luna by default) and its settings, the claim graph and its nodes, the shared pool and a saver per claim run, tracing, and `work_claim`, the one function that works a claim; the queue agent, its middleware and `run_agent` go | `api`, `tools`, LangGraph, LangChain, Langfuse, `psycopg_pool` |
| `agent/dispatcher.py` | new | The dispatcher graph, for dispatches and evaluations | `api`, `harness`, LangGraph, `langchain_core.exceptions` |
| `agent/work.py` | changed | Dispatches and evaluations from start to finish, and stopping runs left running; `run_queue` and `catch_up` go | `api`, `harness`, `dispatcher` |
| `agent/service.py` | changed | The agent's web service: hands each request on and does no work itself | `work`, `harness`, `fastapi` |
| `agent/__main__.py` | changed | `uv run -m agent CLM-1001` works one claim; a claim id is required | `api`, `harness`, `dotenv` |
| `backend/database.py` | changed | The tables above | `sqlalchemy`, `fastapi`, `anyio` |
| `backend/models.py` | changed | The run, dispatch, evaluation, score, cost and time shapes | `pydantic` |
| `backend/seed.py` | changed | Also fills `held_out_claims` and `handler_decisions` from `data/evals/` | `database` |
| `backend/agent_service.py` | renamed from `agent_client.py` | The one client for the agent's service: `resume_claim`, `start_dispatch`, `start_evaluation`, through one `client()` | `httpx`, `fastapi` |
| `backend/usage.py` | new | The router for `record_model_call` and `record_work_time` | `database`, `models`, `run_records` |
| `backend/run_records.py` | new | What the runs and evaluations routers share: creating and finding a run, and a run's claims with their cost and time | `database`, `models` |
| `backend/runs.py` | changed | The router for dispatches and for what every run does: take its claims, finish, stop | `database`, `models`, `run_records`, `agent_service` |
| `backend/evaluations.py` | new | The router for evaluations: start, create with copies, list, get | `database`, `models`, `run_records`, `scoring`, `agent_service` |
| `backend/scoring.py` | new | The scores, as plain functions | `models` |
| `backend/claims.py` | changed | Leaves copies out of the queue and refuses to sign one off | `database`, `settings`, `models`, `agent_service` |
| `backend/documents.py` | changed | `get_instructions` serves only the claim agent's | `database`, `models` |
| `backend/main.py` | changed | Adds the usage and evaluations routers | the routers, `database`, `seed` |
| `dashboard/src/api.ts` | changed | The new types and calls; the to-do list goes | |
| `dashboard/src/components/AgentsForm.tsx` | new | N from 1 to 25, 3 to start with, a start button and the start's answer, for both pages | |
| `dashboard/src/components/RunPanel.tsx` | changed | The latest dispatch: its claims, cost, time and summary | |
| `dashboard/src/pages/QueuePage.tsx` | changed | Adds the start form | |
| `dashboard/src/pages/ScoreboardPage.tsx` | new | Start an evaluation, and the evaluations with their measures | |
| `dashboard/src/pages/EvaluationPage.tsx` | new | One evaluation's claims, handler beside agent, misses marked | |
| `dashboard/src/components/DecisionPanel.tsx` | changed | No sign-off form on a copy | |
| `dashboard/src/pages/InstructionsPage.tsx`, `App.tsx`, `format.ts` | changed | The claim agent's instructions only; the Scoreboard link and routes; percentages, durations and small costs | |
| `e2e/agent-stand-in.ts`, `e2e/api.ts` | changed | The stand-in records the dispatches and evaluations it's asked to start; the helpers play out runs through the API | |

### Fixing the code before building on it

1. The work on one claim (`work_claim`, `carry_on`, `outcome`, `report`, `work_one_claim`) is in `work.py`, but the brief puts the one function the dispatcher calls in the harness. It moves to `harness.work_claim(claim_id, run_id)` before cost and time are added to it (phase 1).
2. `harness.checkpointer()` is one cached `PostgresSaver` per process, and the saver locks around every read and write, so 25 claim agents would take turns. It becomes a cached `pool()` and a new saver per claim graph, with `setup()` run once when the pool opens (phase 2).
3. `backend/agent_client.py` posts with a bare `httpx.post`. It becomes `backend/agent_service.py`, the name in the brief, with one `client()` like `agent/api.py`'s, so the agent's tests can wire the backend to the service in-process (phase 3).
4. The run panel, `e2e/run.spec.ts` and `backend/runs.py` are built on the to-do list, which goes (phases 2 and 3).
5. `agent/tests/test_tracing.py` borrows helpers from `test_queue.py`, which goes with the queue agent (phase 2).
6. Found while building phase 2: in LangGraph 1.2.12 a node's `error_handler` caught a failed `Send` task only when it ran alone. With several `Send` tasks in one step, the runner marked the handled failure as not to be raised again, but the thread executor's `__exit__` never checked that mark and raised it anyway, which would stop the whole dispatch. LangGraph 1.2.22 fixes it, so the project now depends on `langgraph>=1.2.22`.
7. Found while building phase 2: the end-to-end sign-off test read the stand-in's record straight after the page changed, but the backend calls the agent's service in a background task after it answers, so about half the runs read an empty record about 60 ms too early. The test now waits for the call with `expect.poll`.
8. Found while building phase 4: every test run of five claim agents at once hung. The agent's tests built a new `TestClient` for each call to the backend, and each `TestClient` runs its own event loop, so with more claim agents than the backend's four connection slots, a request waiting for a slot on one loop was never woken when another loop freed one: a dispatch at N=5 hung the same way, and the hang went away with slots enough that nobody waited. uvicorn runs every request on one loop, so the tests now share one `TestClient` for the whole test, as the product does, and the dispatcher's test of N at once also runs six claim agents.

### Dashboard

- **Queue page.** Above the run panel, "Claim agents at once" (1 to 25, 3 to start with) and "Start a dispatch". After a start it says "Dispatch started", or shows the refusal: "A dispatch or evaluation is already running" or "The agent's service isn't running".
- **Run panel** ("Dispatch"), refreshing every two seconds: "Dispatch 4, 25 claim agents at once, GPT-6 Luna (low), started at 10:02. Running now." or "Finished at 10:05, after 3m 12s." or "Stopped before it finished." Then the model cost and the claims' total time, and a row per claim: id (linked), state, decision, payout, started, time, cost. Once it isn't running, the summary: "Approved 5, declined 2 and referred 1. Waiting for sign-off: CLM-1008 ($2,240.00). Left for a handler: CLM-1015. Still in progress: none." Before the first dispatch: "No dispatch yet."
- **Scoreboard** (`/scoreboard`): the set (the evaluation set or the held-out set), "Just the five tiny claims", N and "Start an evaluation", with the same answers. Then a row per evaluation, newest first: number, started, set, N, model and effort, state, claims, decision accuracy, accuracy, cost of mistakes, straight-through, cost per claim, time per claim and run time, each opening its evaluation.
- **Evaluation** (`/evaluations/:runId`): the same measures, then a row per claim: the copy (linked to its page), the claim it copies, the handler's decision and payout, the agent's decision, payout and reason, cost and time. A miss is marked on its row: "Wrong decision" or "Wrong amount". A claim with no decision shows "No decision (counts as a referral)".
- **A copy's claim page** says "A copy in evaluation 7" (linked) and has no sign-off form; a held copy says "Held for sign-off. An evaluation's copy is never signed off."
- **Instructions** shows only the claim agent's instructions.

### Connections at once

| Process | At most |
| --- | --- |
| The backend | 4 |
| The agent's service: every claim agent of a dispatch or evaluation and every resume share its pool | 4 |
| `uv run -m agent CLM-1001`, if run beside them | 4 |
| In all | 12 |

### Docs

`docs/SPEC.md`'s sections on working the queue and on what the team needs to see describe the dispatch, the scoreboard and cost and time; its Rules stay as they are. `docs/TECH_STACK.md` describes the dispatcher, GPT-6 Luna and the records. `docs/PROCESS.md` has no five-claim cap today, so it gains the rule that a live run reseeds once first and keeps to the runs its plan names, which replaces the five-claim cap of earlier plans, and says seeding reads `data/evals/` into tables no claim operation reads. `docs/STATUS.md` describes the product and the live runs.

In `docs/CODE_STANDARDS.md`, rule 10 names the five parts: the harness with `work_claim`, the one function the dispatcher calls, and `dispatcher.py`. The brief also names rule 13, but our rule 13 ("Before extending code, check it meets these standards") says nothing about the product. The rule here that names each one-client module is rule 8, so it gains `backend/agent_service.py` as the one client for the agent's service, and rule 13 stays as it is. **To confirm with the user.**

### How the criteria are checked

Tests run on SQLite with an in-memory checkpointer and stub models whose replies carry OpenRouter-style token usage and cost. A dispatcher test can replace `harness.work_claim`, the dispatcher's only way into the claim agent. Retry waits are set to zero in the tests. Against `npm run dev`, phases 1 to 5 call no model: API calls with `curl`, pages through the Playwright MCP server, and Supabase through its read-only MCP server. The only live runs with the real model are the four in phase 6, after one reseed: a dispatch at N=3 that is killed, a dispatch at N=25, and two evaluations. Langfuse is checked through its API with a short `uv run python -c` that uses `get_client().api`.

## Phase 1: GPT-6 Luna, and the cost and time of each claim

Move the work on one claim into `harness.work_claim(claim_id, run_id)`; the queue agent, the command line and the service call it. Make GPT-6 Luna the default model. Add `model_calls` and `work_times`, with `record_model_call` and `record_work_time` in `backend/usage.py`. Give the claim graph a runtime context with the run id (`context_schema`), and have the `agent` node record each reply's tokens and cost. `harness.work_claim` records each piece of work's time. Until phase 2 the run is the queue agent's run.

- [x] pytest: with no `MODEL_NAME`, `harness.model()` is `openai/gpt-6-luna` with reasoning effort `low`, and the model settings are `("openai/gpt-6-luna", "low")`. With `MODEL_NAME=openrouter/free`, it's that model with no reasoning effort, and the settings are `("openrouter/free", "none")`
- [x] `grep -rn "deepseek-v4.1-flash" agent backend` finds nothing
- [x] `grep -n "def work_claim\|def carry_on\|def outcome\|def report" agent/*.py` finds them only in `agent/harness.py` (apart from the queue agent's `work_claim` tool, which goes in phase 2), and every existing stub model test passes on `harness.work_claim`
- [x] pytest: `record_model_call` stores the tokens and cost with a run, or with none when `run_id` is null. 404 for an unknown claim or run, 422 for negative tokens or cost or a missing field
- [x] pytest: `record_work_time` stores the start and seconds with a run or with none. 404 for an unknown claim or run, 422 for negative seconds
- [x] Stub model test: a claim worked on its own records one model call per reply, with the stub's tokens and cost, and one piece of work, all with no run
- [x] Stub model test: a claim worked in a queue run records its model calls and its time with that run
- [x] Stub model test: a claim that fails and is tried again has both tries' model calls and time recorded with the run
- [x] Stub model test: a claim held for sign-off, then signed off after the test waits 2 seconds and paid through the service, has two pieces of work, the first with the run and the pay with no run, adding up to under 2 seconds. The pay records no model call
- [x] The tracing tests still pass: each model call puts OpenRouter's cost on its generation
- [x] The OpenAPI test passes with the two operations
- [x] `npm run check` passes

## Phase 2: The dispatcher in place of the queue agent

Reshape `runs` and add `run_claims`, with `create_dispatch`, `get_latest_dispatch`, `take_claims`, `finish_run` and `stop_runs`. Build `agent/dispatcher.py` and `work.dispatch`. Give each claim graph a saver of its own on the shared pool. Tag each claim's trace with its run. The service gets `start_dispatch` and stops unfinished runs on startup. Remove the queue agent, its middleware, `queue.md`, the to-do list, its e2e test and `uv run -m agent` without a claim id. The run panel shows the latest dispatch's line, and the instructions page only the claim agent's. Update rule 10.

- [x] pytest: `create_dispatch` returns a running dispatch with its N, model and effort. `get_latest_dispatch` is null before the first, then the newest. N of 0 or 26 returns 422
- [x] pytest: on a dispatch, `take_claims` returns the queue's claims in progress and waiting, oldest submitted first, leaving out claims decided, waiting for sign-off or left for a handler and the claims in `skip`, and records them on the run. 409 for a run that isn't running, 404 for an unknown run
- [x] pytest: `finish_run` finishes a running run and returns 409 the second time. `stop_runs` marks every running run stopped and leaves finished ones alone
- [x] pytest: a dispatch played out through the API, with an approval paid, an approval held, a decline, a referral, a claim left for a handler and a claim in progress, has in `get_latest_dispatch` each claim with its state, decision, payout, first start, time and cost, the model cost as the sum of its model calls, and once finished the summary: approved 2, declined 1, referred 1, the held claim and payout, the claim left for a handler and the claim in progress. A running dispatch has no summary
- [x] A pytest test checks the dispatcher's nodes are `list_claims`, `work_claim`, `list_retries` and `retry_claim`, with the edges in the design
- [x] Dispatcher test, with `harness.work_claim` replaced by a recorder that sleeps briefly: over 10 claims, N=3 never has more than 3 at once and reaches 3, and N=1 works one at a time
- [x] Stub model test: a dispatch at N=3 works every waiting claim, starting them oldest submitted first, with one decision each, and finishes the run
- [x] Stub model test: claims left in progress by a stopped claim graph are carried on by the next dispatch as the same attempts: the same thread, failure count 0, no `error` step, the earlier steps kept and one decision
- [x] Stub model test: a claim whose model raises `ModelRateLimitError` three calls running, past the `agent` node's two retries, waits and carries on from its last saved step on the same thread, with one decision, no `error` step and failure count 0, and both pieces of its work are recorded with the run
- [x] Stub model test: a claim that hits rate limits on every call stays in progress after the worker's retries run out, with failure count 0 and no `error` step, while the other claims are decided, the dispatch finishes, and its summary has the claim still in progress
- [x] Stub model test: a claim that fails with any other error goes back to the queue and is tried once more after the first round, on a new thread, and decided. A claim that fails both times is left for a handler, and the dispatch still finishes
- [x] Stub model test: a claim in `skip` is not taken or worked. A claim held for sign-off waits, and the next dispatch doesn't take it
- [x] pytest: the model class, given an HTTP transport that answers 429 or times out, raises `ModelRateLimitError` or `ModelTimeoutError`, without calling a model
- [x] pytest: two claim graphs get two different savers on the one pool, which holds at most 4 connections and waits for a free one longer than psycopg_pool's default 30 seconds
- [x] Tracing test: a claim worked in a dispatch is one `work-claim` trace in its session, tagged `run-<run id>`, and a claim worked with no run has no tag
- [x] Service tests: `start_dispatch` returns 202 and works the dispatch in the background. While a run is going, a second start returns 409 "A dispatch or evaluation is already running". Its operations follow the API rules
- [x] Service test: starting the service marks a running dispatch stopped
- [x] Tests cover the command line: a claim id in progress is carried on, a waiting one is started, and with no claim id it prints its usage and exits with an error
- [x] `grep -rn "queue_agent\|write_todos\|MissedClaimsCheck\|run_queue\|catch_up\|todos\|create_agent\|AgentMiddleware" agent backend dashboard/src e2e` finds nothing, and `backend/instructions/queue.md` is gone
- [x] vitest: the run panel shows "No dispatch yet", then the latest dispatch's line with its N and whether it's running, finished or stopped. The instructions page shows only the claim agent's instructions
- [x] `npm run seed` works, and through the Supabase MCP server `undercover.runs` has the new columns and no `todos`, and `run_claims`, `model_calls` and `work_times` exist
- [x] With `npm run dev`, `curl -s -X POST localhost:8000/api/dispatches` (standing in for the service) makes a running dispatch, and starting `npm run dev` again leaves it stopped in `curl -s localhost:8000/api/dispatches/latest`. No model is called. (Touching `agent/service.py` was the first try: uvicorn's reloader stops its worker on Windows with a Ctrl+C sent to the console, and `npm run dev` started from a shell with no console never gets it, so the old worker kept running. In a terminal the reload works as usual.)
- [x] `npm run dev` started five times on Windows, with a dispatch left running before each start, comes up every time in 7 to 8 seconds with `curl -s localhost:8002/api/health` returning `{"status": "ok"}`, and each time the dispatch left running is stopped
- [x] `docs/CODE_STANDARDS.md` rule 10 names the five parts of the agent
- [x] `npm run check` passes

## Phase 3: Starting a dispatch from the dashboard

Rename `backend/agent_client.py` to `backend/agent_service.py`, with one `client()`, and add `start_dispatch`. The backend's `start_dispatch` asks the service and relays its answer. The queue page gets the start form, and the run panel shows the dispatch's claims, cost, time and summary. The e2e stand-in records the starts it's asked for, and a new `e2e/dispatch.spec.ts` replaces `run.spec.ts`.

- [x] pytest: the backend's `start_dispatch` with N=5 asks the service once with 5, returns 202 and creates no run
- [x] pytest: with `UNDERCOVER_AGENT` pointing at a port nothing listens on, `start_dispatch` returns 503 "The agent's service isn't running"
- [x] pytest, with the backend wired to the service in-process: while a run is going, the backend's `start_dispatch` returns 409 "A dispatch or evaluation is already running"
- [x] pytest: N of 0 or 26 returns 422 from the backend's `start_dispatch`
- [x] The existing sign-off tests pass through `agent_service.resume_claim`
- [x] `grep -rn "UNDERCOVER_AGENT\|/resume\|8002" backend --include=*.py` finds them only in `backend/agent_service.py` and the tests
- [x] vitest: the start form starts at 3, keeps N between 1 and 25, starts a dispatch with the N chosen and says "Dispatch started", and shows the 409 and 503 messages
- [x] vitest: the run panel shows a running dispatch's claims with their states and its cost so far; a finished one with its run time, cost and the summary in sentences; a stopped one as stopped, with its summary
- [x] e2e: on the queue page the handler sets 5 and starts a dispatch; the stand-in on port 8003 has been asked for a dispatch with 5 agents, and the page says it started
- [x] e2e: the test plays out a dispatch through the API, as `run.spec.ts` did with a run: it creates the dispatch, takes two claims while skipping the rest, works one to a decision and fails the other, records a model call and a piece of work on each and finishes the dispatch. Without a reload, the panel shows the two claims and where each stands, the model cost, the time and the summary
- [x] e2e: the other tests still pass, and the to-do list test is gone
- [x] In the browser, with only `npm run dev:backend` and `npm run dev:dashboard` running, "Start a dispatch" shows "The agent's service isn't running", and `browser_console_messages` shows no errors other than the refused request
- [x] `npm run check` passes

## Phase 4: Evaluations

Seed `held_out_claims` and `handler_decisions` from `data/evals/`. Add `evaluation_id` and `source_id` to `claims` and `eval_set` and `tiny` to `runs`. Build `create_evaluation` with the copies, `take_claims` for an evaluation, `backend/scoring.py`, `list_evaluations`, `get_evaluation` and the backend's `start_evaluation`. Leave copies out of the queue and refuse to sign one off. The service gets `start_evaluation`, and `work.evaluate` clears each copy's saved progress.

- [x] pytest: seeding stores 25 held-out claims and 50 handler decisions, 25 for each set with 5 `tiny` in each, and the queue still holds 25 claims
- [x] `grep -rln handler_decisions backend agent` finds only `backend/database.py`, `backend/seed.py`, `backend/evaluations.py` and the tests, and `grep -rn "evals" agent` finds nothing
- [x] pytest: `create_evaluation` of the evaluation set makes 25 copies, its `tiny` claims 5 (copies of CLM-1007, CLM-1015, CLM-1017, CLM-1020 and CLM-1021), and the held-out set's `tiny` claims copies of CLM-1104, CLM-1106, CLM-1110, CLM-1112 and CLM-1114. Each copy is waiting, with a new id written into its record, and `list_claims` returns the same 25 claims as before
- [x] pytest: `get_claim` on a copy has its new id and its `evaluation_id`, the same fields as a queue claim, and none of the handler's decision, payout, reason, reference or calculation
- [x] pytest: signing off a copy held for sign-off returns 409, and the copy stays held
- [x] pytest: `take_claims` on an evaluation returns its copies, oldest submitted first, and on a dispatch never a copy
- [x] pytest: the scoring functions on hand-worked cases: a right approval within a dollar, a right approval $40 out, a wrongful decline, a wrongful approval paid and one held, a needless referral, a claim with no decision counted as a referral, and the run's measures from them
- [x] pytest: an evaluation of the five `tiny` claims of the evaluation set, played out through the API with decisions, model calls and work times, has in `list_evaluations` and `get_evaluation` the measures worked out by hand in the test, and each claim with the handler's decision and payout beside the agent's, the agent's reason, cost and time
- [x] pytest: `list_evaluations` is newest first, and a stopped evaluation shows as stopped with no run time
- [x] Stub model test: `work.evaluate` at N=5 on the five `tiny` claims, with a stub that decides each copy and approves one over $1,000, leaves `list_claims` exactly as it was, decides or holds every copy, records the set, N, model and effort, counts the held copy as an approval with its payout, clears every copy's thread from the checkpointer, and finishes the evaluation
- [x] Stub model test: a dispatch after an evaluation takes no copy
- [x] Service tests: `start_evaluation` returns 202 and runs the evaluation, and 409 while a run is going. The backend's `start_evaluation` asks the service once with N, the set and `tiny`, returns 503 when the service isn't running, and 422 for an unknown set
- [x] The OpenAPI tests pass for the backend and the service
- [x] `npm run seed` works, and through the Supabase MCP server `undercover.held_out_claims` has 25 rows, `undercover.handler_decisions` 50, and the queue 25 waiting claims
- [x] `npm run check` passes

## Phase 5: The scoreboard

Build the Scoreboard and evaluation pages, the Scoreboard link, and a copy's claim page without the sign-off form. A new `e2e/scoreboard.spec.ts` starts an evaluation and plays one out.

- [ ] vitest: the scoreboard's form sends the set, `tiny` and N (3 to start with) and says "Evaluation started", or shows the 409 and 503 messages
- [ ] vitest: the scoreboard lists evaluations newest first, with the set, N, model and effort, state and every measure formatted, each linking to its evaluation, and a stopped one marked stopped
- [ ] vitest: the evaluation page shows each claim with the handler's decision and payout beside the agent's, marks a wrong decision and a wrong amount, says a claim with no decision counts as a referral, and links each copy to its page
- [ ] vitest: a copy's decision panel has no sign-off form and, when held, says an evaluation's copy is never signed off
- [ ] e2e: on the scoreboard the handler chooses the held-out set, just the five `tiny` claims and N=5, and starts an evaluation; the stand-in has been asked for an evaluation of the held-out set, `tiny`, with 5 agents
- [ ] e2e: the test plays out an evaluation of the evaluation set's `tiny` claims through the API, with one right approval, one wrong decision, one approval over $1,000 held, one wrong amount and one claim left undecided, and finishes it. The scoreboard shows it with every measure; it opens to its claims with the misses marked; a copy's link opens its claim page, where the held copy has no sign-off form
- [ ] e2e: the queue page's counts are the same before and after the evaluation
- [ ] e2e: the header has Queue, Scoreboard and Instructions, and the other tests still pass
- [ ] `npm run check` passes

## Phase 6: The live runs, and the docs

With the default model, after one `npm run seed`, with `npm run dev` running. Before starting, `.env` sets no `MODEL_NAME` (checked by its key only), and the processes listening on ports 8000 and 8002 are the ones `npm run dev` started.

- [ ] Live: on the queue page, through the Playwright MCP server, a dispatch at N=3 starts, and the run panel shows three claims in progress at a time, recorded as `openai/gpt-6-luna` with effort `low`
- [ ] Live: once a few claims are decided and three are in progress, every process listening on port 8002 is killed with `taskkill /F` (from `netstat -ano`), the Windows equivalent of `kill -9`, nothing listens on 8002 afterwards, and `npm run dev` stops the others. `npm run dev` starts again, and the run panel shows the dispatch stopped, with its claims in progress
- [ ] Live: a dispatch at N=25 carries on the claims left in progress as the same attempts (the same thread, failure count 0, no `error` step, the earlier steps kept, one decision each) and works the rest with 25 at once: every claim's first start in the run is within a few seconds of the dispatch's start
- [ ] Live: the N=25 dispatch's run time is well under its claims' total time. Claims worked from the start take about as long as those at N=3, compared by median; if they are slower, a report of where the time goes, from Langfuse's timings of the model calls and the tools, still with 4 connections in each process
- [ ] Live: during the N=25 dispatch, signing off a claim the first dispatch held, as Dana Whitfield on its claim page, shows it decided and paid within five seconds. The other held claims still wait
- [ ] Live: checked several times during the N=25 dispatch through the Supabase MCP server, `pg_stat_activity` never shows more than 12 connections whose user is `postgres`, and no claim has an `error` step about a database connection
- [ ] Live: the finished dispatch's panel shows its summary, model cost and time. Its model cost equals the sum of its `model_calls` rows, each with tokens and a cost above zero, and one claim's cost equals what Langfuse records for its trace
- [ ] Live: the queue page's counts are noted. An evaluation of the evaluation set at N=25, and one of the held-out set's five `tiny` claims at N=5, both started on the scoreboard, appear there with every measure, the model and the effort, and open to their claims. The queue page's counts are the same afterwards
- [ ] Live: through Langfuse's API, the traces tagged `run-<the N=25 dispatch's id>` include a trace for each claim it worked
- [ ] `docs/SPEC.md`'s sections on working the queue and on what the team needs to see describe the dispatch, the scoreboard and cost and time, and its Rules are unchanged. `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` (rule 10, and rule 8 or 13 as confirmed) and `docs/STATUS.md` describe the product as it now is, including these live runs
- [ ] With `.env` moved out of the way, `npm run check` passes

## Not in this plan

- Cancelling a dispatch or an evaluation from the dashboard, or deleting an evaluation.
- Scores in Langfuse, as the lab sends them.
- The dispatcher saving progress of its own. Each claim saves its own, and the next dispatch finishes what a stopped one left.
- Clearing the checkpoints of copies left by an evaluation that stopped partway, or of old threads. Nothing ever picks them up.
- Evaluations of `data/evals/harder` or `data/evals/even_harder`.
- Coordinating `uv run -m agent CLM-1001` with a dispatch working the same claim, beyond the backend's rules that nothing is decided or paid twice.
- Running the tests on Postgres.
- Deploying the agent to the cloud. `harness.work_claim` is the seam for it.
