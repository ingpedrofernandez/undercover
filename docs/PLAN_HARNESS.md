# Plan: the harness

This plan builds the brief in `HARNESS.md` on top of the finished pilot, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

When it's done, one command starts the UnderCover Agent on the queue. The agent plans its run as a to-do list that the queue page shows, and hands each claim to a fresh claim agent that looks up the sections of the policy wording and the claims manual it needs. A claim that fails goes back in the queue, a claim that fails twice is left for a handler, and the run checks it has missed nothing before it writes its summary.

## Design

### Two agents

| | The queue agent | The claim agent |
| --- | --- | --- |
| Job | Plans the run, works the queue one claim at a time and writes the summary | Works one claim from a clean start |
| Tools | `list_claims`, `write_todos`, `work_claim` | `get_claim`, `get_policy`, `get_claim_history`, `list_sections`, `search_documents`, `read_section`, `record_decision`, `pay_claim` |
| Instructions | `backend/instructions/queue.md` | `backend/instructions/claim.md` |
| Remembers | Its plan and one line per claim | Only its own claim |

Both use LangChain's `create_agent`, as the pilot does. No other agent framework.

`work_claim` is how the queue agent hands a claim to the claim agent, like Deep Agents' `task` tool in the Day 5 lab. Every other tool is named after the backend operation it calls.

Why two agents: the queue agent's conversation grows by one line per claim instead of by every document of every claim, so each step stays cheap as the run goes on, and each claim gets the claim agent's full attention.

### Who guarantees what

The instructions tell the agents what to do. The harness code and the backend make sure the rules hold even when a model gets something wrong.

| Rule from the brief | Enforced by |
| --- | --- |
| A run takes on no more claims than its cap | `work_claim` refuses a new claim once the cap is reached. A retry of a claim already taken on in this run doesn't count again |
| One bad claim never stops the run | `work_claim` catches whatever the claim agent raises, records the failure and returns a line. The queue agent carries on |
| A claim never stays stuck in progress | `work_claim` records a failure when the claim agent raises, or when it ends without recording a decision |
| A failed claim goes back in the queue, and a second failure leaves it for a handler | The backend's `record_failure`, which counts failures on the claim |
| No claim is decided or paid twice | The backend: `start_claim` needs a waiting claim, `record_decision` needs a claim in progress, `record_failure` needs a claim in progress, and `pay_claim` refuses a second payment |
| The run doesn't miss a waiting claim within its cap | The missed-claims check (below) |
| Claims are worked one at a time | `work_claim` holds a lock, since a model can ask for several tool calls in one turn |

### Claim states

One new state joins the pilot's four.

| State | Meaning | Label on screen | Color |
| --- | --- | --- | --- |
| `waiting` | In the queue, not started, or back after one failure | Waiting | Cerulean |
| `in_progress` | The claim agent is working on it | In progress | Marigold |
| `waiting_for_sign_off` | Approved over the limit, payment held | Waiting for sign-off | Coral |
| `decided` | Decided, and paid if approved within the limit or signed off | Decided | Sea Green |
| `left_for_handler` | Failed twice before it was decided | Left for a handler | Raspberry |

### Problems and how they're put right

- **A slow or failed model call.** The model has a 120-second timeout, and the client's own retries are off so retrying happens in one place: `ModelRetryMiddleware` retries a failed call twice with backoff, then raises.
- **A claim agent that goes round in circles.** `ModelCallLimitMiddleware` stops a claim after 30 model calls by raising.
- **A claim that fails.** `work_claim` calls `record_failure` with the error, and the claim goes back to `waiting`. The queue agent tries it again after the other claims. A second failure moves it to `left_for_handler`. The failure count lives on the claim, so a claim that failed once in an earlier run is left for a handler if it fails again.
- **A claim that fails after it's decided**, for example on the claim agent's final reply. It stays decided and is never worked again. Its line says so, including "not paid" for an approval within the limit that was never paid, so the summary can flag it.
- **The queue agent itself fails.** The run is finished with a summary that says it stopped early and why. No claim is left in progress, since `work_claim` has already put right the claim it was on.
- **The queue agent tries to finish too early.** See the missed-claims check.

### The missed-claims check

An `after_model` middleware on the queue agent. When the queue agent replies without calling a tool, which is how it finishes, the check calls `list_claims`. If a claim it took on is back in the queue after a failure, or claims are still waiting and the run is under its cap, it adds a message naming them and how many more claims the run can take on, and sends the agent back to work. Otherwise the agent finishes. The queue agent's `ModelCallLimitMiddleware` (200 calls) is the backstop if it never settles.

Why in code: "checks that it has not missed a waiting claim" has to hold every time, and a model's promise to check isn't a guarantee. The instructions also tell the agent to check `list_claims` before it finishes, so the harness rarely has to step in.

### The one-line report

`work_claim` builds its line from the backend's record of the claim after the claim agent finishes, not from what the claim agent says, so the queue agent sees the truth. It also prints the line, so the console shows the run's progress.

```
CLM-1001  approve  $420.00  paid
CLM-1002  approve  $1,350.00  waiting for sign-off
CLM-1003  refer  $0.00
CLM-1004  failed: Request timed out. Back in the queue.
CLM-1004  failed again: Request timed out. Left for a handler.
CLM-1006  not started: the run's cap of 5 claims is reached
```

### Runs and the to-do list

A run is stored in the backend so the dashboard can show it. It has an id, its cap, start and finish times, the summary and the to-do list. Each to-do item has `content` and a `status`: `to_do`, `in_progress`, `done` or `left_for_handler`, shown as To do (Cerulean), In progress (Marigold), Done (Sea Green) and Left for a handler (Raspberry).

`write_todos` replaces the whole list each time, the same shape as LangChain's `TodoListMiddleware`. We don't use that middleware because it keeps the list inside the agent where the dashboard can't see it, and it has no "left for a handler" status.

### Looking things up

Seeding splits `policy_wording.md` and `claims_manual.md` into their numbered `## ` sections, stored in a `sections` table. The lines before section 1 are section 0, titled with the document's `# ` title. The documents are `policy_wording` (sections 0 to 12) and `claims_manual` (sections 0 to 14).

The claim agent works like a handler with the manual open: it looks at the contents, searches for a word, and reads the sections it needs. Neither document goes into its prompt.

When the claim agent reads a section, the step is recorded as a `read` step in place of the tool result. Its first line names the section, such as `Claims manual, section 7: Interpretation notes`, and the section's text follows. A refused read stays an ordinary tool result. The claim page lists the `read` steps under "What the agent read".

### API

New and changed operations. Every operation keeps an `operation_id`, a one-line docstring and no optional inputs.

| Operation | Route | What it does |
| --- | --- | --- |
| `list_sections` | `GET /api/documents/{document}/sections` | The contents: each section's document, number and title |
| `search_documents` | `GET /api/documents/search?query=` | Sections of either document with a line containing the query, ignoring case, with those lines |
| `read_section` | `GET /api/documents/{document}/sections/{section}` | One section: document, number, title and text |
| `record_failure` | `POST /api/claims/{claim_id}/failure` | Body `{reason}`. Records a failed try on a claim in progress |
| `start_run` | `POST /api/runs` | Body `{limit}`. Starts a run capped at `limit` claims |
| `write_todos` | `PUT /api/runs/{run_id}/todos` | Body `{todos}`. Replaces the run's to-do list |
| `finish_run` | `POST /api/runs/{run_id}/finish` | Body `{summary}`. Finishes the run |
| `get_latest_run` | `GET /api/runs/latest` | The most recent run, or `null` before the first |
| `get_instructions` | `GET /api/instructions` | Now `{queue, claim}`: the two sets of instructions, without the policy wording |

Rules the backend enforces:

- Sections: an unknown document or section returns 404, and an empty query returns 422. A search with no match returns an empty list.
- `record_failure` needs a claim in progress (409) and a reason (422). It records an `error` step with the reason. A first failure moves the claim to `waiting`, a second to `left_for_handler`.
- `start_run` needs a limit of at least 1 (422). `write_todos` and `finish_run` need a run that isn't finished (409). Unknown runs return 404. A to-do item needs content and a known status, and a summary can't be empty (422).
- `get_latest_run` returns `null` rather than 404, so the queue page keeps refreshing when it's opened before the first run.

The new routes live in `backend/documents.py` and `backend/runs.py`, so `backend/main.py` stays short.

### Agent code

- `agent/tools.py`: the claim agent's tools.
- `agent/main.py`: the model, the claim agent's `run(claim_id, thread_id)`, and `work_claim(claim_id)`, which starts the claim, runs the claim agent, records a failure when needed and returns the line.
- `agent/queue.py`: the queue agent, its tools for one run, the missed-claims check and `run_queue(limit)`, which starts the run, works it and finishes it with the queue agent's last message as the summary.
- The model is DeepSeek V4.1 Flash (`deepseek/deepseek-v4.1-flash`) with low reasoning effort, or `MODEL_NAME` when set.

The command line:

- `uv run -m agent` works every waiting claim: the cap is the number waiting when the run starts. With nothing waiting it says so and starts no run.
- `uv run -m agent --limit 5` caps the run at five claims.
- `uv run -m agent CLM-1001` works one claim with `work_claim` and prints its line.

### Instructions

Written from the policy wording and the claims manual, never from `data/evals/`, which stays closed.

- **The claim agent** follows the order in section 4 of the manual. It finds the benefit in the wording, then reads that section, the general exclusions (section 9) and how we work out the payment (section 10). From the manual it reads the required documents (5), the payout (6), the interpretation notes (7), what to do when the story and the documents disagree (8), repeat claims (9) and meals without receipts (10) when the claim calls for them, and searches for anything else. The wording comes first, and the manual covers what the wording leaves open. It records the section it relied on, from either document.
- **The queue agent** lists the claims, plans a to-do list with one item for each claim it will take on within its cap and a last item for the summary, and chooses the order. It marks each item in progress, hands the claim to `work_claim`, and marks it done or left for a handler from the line it gets back. It tries a claim that's back in the queue again after the others. It never decides a claim itself. Before finishing it checks `list_claims`, then writes a short summary for the handlers: the decisions, the payouts waiting for sign-off, the claims left for a handler and why, and how many are still waiting.

### Dashboard

- **Queue page**: a fifth tile for Left for a handler, and a panel with the agent's to-do list for the latest run: when it started, its cap, whether it's running or finished, each item with its status, and the summary once it's finished. It refreshes every two seconds with the rest of the page.
- **Claim page**: "What the agent read" lists the sections the claim agent read, once each, in the order it read them. The step list shows `read` steps folded to their first line, and `error` steps as failures. The decision panel says when a claim is left for a handler.
- **Instructions page**: two parts, "Running the queue" and "Working a claim", still read only.

### How the criteria are checked

As in the pilot: API calls against `npm run dev` on a freshly seeded database, and pages in the browser with the Playwright MCP server at `http://localhost:5173`. Tests never call a model; they use stub models, as `agent/tests/test_agent.py` does. Only the criteria marked "Live" use the real model, and every live run starts with `uv run -m backend.seed` and works at most five claims.

## Phase 1: The wording and the manual, section by section

Seed the `sections` table from both documents and add `list_sections`, `search_documents` and `read_section`. Backend only, so the lookups can be checked before any agent uses them.

- [x] pytest covers splitting a document into sections, each new operation, and each 404 and 422 below
- [x] `curl -s localhost:8000/api/documents/claims_manual/sections` returns 15 sections numbered 0 to 14. Section 9 is "Repeat claims" and section 14 is "Records"
- [x] `curl -s localhost:8000/api/documents/policy_wording/sections` returns 13 sections numbered 0 to 12. Section 10 is "How we work out your payment"
- [x] `curl -s localhost:8000/api/documents/claims_manual/sections/10` returns the title "Meals without receipts" and text that includes "$35 per traveler"
- [x] `curl -s "localhost:8000/api/documents/search?query=monkey"` returns one section, `claims_manual` section 7 "Interpretation notes", with its one line about wild animals. `query=MONKEY` returns the same
- [x] `query=third%20claim` returns only `claims_manual` section 9, with two lines
- [x] `query=zebra` returns `[]`
- [x] An unknown document and an unknown section each return 404, and `query=` returns 422
- [x] The OpenAPI test passes with the new operations
- [x] `grep -rn evals backend agent dashboard/src` finds nothing
- [x] `npm run check` passes

## Phase 2: The claim agent looks things up

Give the claim agent `list_sections`, `search_documents` and `read_section`. Rewrite its instructions as `backend/instructions/claim.md`, written from the wording and the manual, and serve them without the policy wording: `get_instructions` returns `{claim}`, and the wording leaves the settings table. Record reads as `read` steps and show them on the claim page. Make DeepSeek V4.1 Flash the default model. Update `docs/SPEC.md` for the manual and `docs/TECH_STACK.md` for the model.

- [ ] A pytest test checks the claim agent's tools are exactly `get_claim`, `get_policy`, `get_claim_history`, `list_sections`, `search_documents`, `read_section`, `record_decision` and `pay_claim`, each named after a backend operation
- [ ] Stub model test: the system prompt is the `claim` text from `get_instructions`, and it contains neither "## 10. How we work out your payment" nor "$35 per traveler"
- [ ] Stub model test: the stub calls `search_documents` (monkey), `read_section` (claims_manual, 7), then decides. The steps hold the search as a tool call and result, then a `read` step whose first line is `Claims manual, section 7: Interpretation notes` and no separate tool result for that read
- [ ] Stub model test: `read_section` for section 99 reaches the model as a refusal and is recorded as a `tool_result`, not a `read`
- [ ] The model test checks the default is `deepseek/deepseek-v4.1-flash` with low reasoning effort, and that `MODEL_NAME` overrides it
- [ ] vitest covers `read` steps folded to their first line, and "What the agent read" listing each section once, in the order read
- [ ] e2e: the test starts `CLM-1005` and records a `read` step through the API. Without a reload, the claim page shows the section under "What the agent read"
- [ ] e2e: the instructions page shows "You are the UnderCover Agent" and no longer shows the policy wording
- [ ] Live: on a fresh database with `npm run dev` running, `uv run -m agent CLM-1020` (sunglasses taken by a monkey) prints a reply
- [ ] Live: `curl -s localhost:8000/api/claims/CLM-1020/steps` shows at least one `list_sections` or `search_documents` call and a `read` step for `Claims manual, section 7`, and the claim has a decision with a section and a reason
- [ ] Live, in the browser: `/claims/CLM-1020` shows the sections under "What the agent read"
- [ ] `docs/SPEC.md` no longer lists the claims manual under "Not for now", and `docs/TECH_STACK.md` names DeepSeek V4.1 Flash
- [ ] `npm run check` passes

## Phase 3: A failed claim is put right

Add `record_failure`, the `left_for_handler` state and `error` steps. Build `work_claim` and its one-line report. Add `ModelRetryMiddleware`, `ModelCallLimitMiddleware` and the timeout to the claim agent. `uv run -m agent CLM-1001` and the pilot's `work_queue` now go through `work_claim`, until phase 5 replaces `work_queue`. Show the new state and failures on the dashboard.

- [ ] pytest: `record_failure` on a waiting, decided or held claim returns 409, and an empty reason returns 422
- [ ] pytest: a first failure moves a claim to `waiting` with an `error` step naming the reason. Starting it again gives it a new thread id. A second failure moves it to `left_for_handler`, and `start_claim` and `record_decision` on it then return 409
- [ ] Stub model test: the claim agent raises a model error. The claim is back in `waiting` and the line is `CLM-1001  failed: <the error>. Back in the queue.`
- [ ] Stub model test: the claim agent ends without recording a decision. The failure reason says it finished without a decision
- [ ] Stub model test: a claim that fails a second time is `left_for_handler` and its line ends `Left for a handler.`
- [ ] Stub model test: a model call that fails once is retried, the claim is decided, and no failure is recorded
- [ ] Stub model test: a claim agent that keeps calling `get_claim` is stopped at 30 model calls and its claim goes back in the queue
- [ ] Stub model test: the stub records a decision and then fails on its final reply. The claim stays decided, no failure is recorded, and the line gives the decision
- [ ] Stub model test: `work_claim` on a claim that isn't waiting returns a "not started" line and changes nothing
- [ ] Tests cover each line in "The one-line report", including "paid", "waiting for sign-off" and "not paid"
- [ ] vitest covers the Left for a handler chip and tile, `error` steps, and the decision panel for a claim left for a handler
- [ ] e2e: the test starts `CLM-1015`, records a failure, starts it again and records a second failure through the API. Without a reload, the page shows Left for a handler and both failures
- [ ] Browser, with `browser_evaluate`: the Left for a handler chip is Raspberry with white text
- [ ] `npm run check` passes

## Phase 4: Runs and the to-do list

Add the `runs` table, `start_run`, `write_todos`, `finish_run` and `get_latest_run`, and the to-do list panel on the queue page. Built before the queue agent so the dashboard can be checked by driving the API by hand.

- [ ] pytest covers every run rule in the design, including each 404, 409 and 422
- [ ] Walked through with curl on a fresh database: `get_latest_run` returns `null`. `start_run` with limit 5 returns run 1 with no to-do items and no finish time. `write_todos` with three items returns them in order. `finish_run` sets the finish time and summary. `write_todos` afterwards returns 409. A second `start_run` becomes the latest run
- [ ] The OpenAPI test passes with the new operations
- [ ] vitest covers the panel with no run, a running run and a finished run with its summary, and the list updating on refresh (with fake timers)
- [ ] e2e: the queue page is open before the test starts a run through the API. Without a reload, the page shows the to-do items, then shows them ticked off as the test updates them, then shows the summary when the test finishes the run
- [ ] Browser, with `browser_evaluate`: each to-do status has the color from the design
- [ ] Browser: screenshots of the queue page in light and dark mode show the panel rounded with no outline, and `browser_console_messages` shows no errors
- [ ] `npm run check` passes

## Phase 5: The agent runs the queue

Build the queue agent in `agent/queue.py`: its tools, the cap, the lock, the missed-claims check, and finishing the run with its summary. Write `backend/instructions/queue.md`, return `{queue, claim}` from `get_instructions`, and show both on the instructions page. Add `--limit` to the command line and remove the pilot's `work_queue`.

The stub model tests use a scripted queue agent and claim agents scripted per claim, on a database where only `CLM-1001`, `CLM-1002` and `CLM-1003` are waiting.

- [ ] A pytest test checks the queue agent's tools are exactly `list_claims`, `write_todos` and `work_claim`, the first two named after backend operations
- [ ] Stub model test: the queue agent's system prompt is the `queue` text from `get_instructions`, and its first message gives the run's cap
- [ ] Stub model test, the to-do list: the stub writes three items, then marks them in progress and done as it works. `get_latest_run` shows the final list, the summary is the stub's last message, and the run is finished
- [ ] Stub model test, the cap: with a cap of 2, the stub asks for all three claims. The third gets the "not started" line and stays waiting with no steps, and the missed-claims check lets the run finish
- [ ] Stub model test, a failure doesn't stop the run: the claim agent fails on `CLM-1001`, and `CLM-1002` and `CLM-1003` are still worked and decided
- [ ] Stub model test, tried again: `CLM-1001` fails once, the stub works the others, then `CLM-1001` again, which is decided. With a cap of 3, all three are decided, since the retry doesn't count against the cap
- [ ] Stub model test, failed twice: `CLM-1001` fails on both tries and is `left_for_handler`, and the run finishes with the other two decided
- [ ] Stub model test, the missed-claims check: the stub tries to finish after two claims. It receives a message naming `CLM-1003`, works it and then finishes. When nothing is missed, it finishes at its first try
- [ ] Stub model test: two `work_claim` calls in one turn are worked one after the other, and both count against the cap
- [ ] Stub model test: when the queue agent fails, the run is finished with a summary saying it stopped early, and no claim is in progress
- [ ] Tests cover the command line: no arguments caps the run at the number of waiting claims, `--limit 5` caps it at five, a claim id works one claim, and with nothing waiting it says so and starts no run
- [ ] `curl -s localhost:8000/api/instructions` returns `queue` and `claim`
- [ ] vitest and e2e: the instructions page shows "Running the queue" and "Working a claim", with no text box, input or edit button
- [ ] `grep -rn evals backend agent dashboard/src` finds nothing
- [ ] `npm run check` passes

## Phase 6: A trial on five claims

Run the harness on the real model, capped at five claims, and watch it on the dashboard. Bring `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` up to date with the product as it now is.

- [ ] Live: after `uv run -m backend.seed`, with `npm run dev` running, `uv run -m agent --limit 5` prints five claim lines and a summary
- [ ] Live: afterwards `curl -s localhost:8000/api/claims` shows five claims worked, 20 waiting and none in progress
- [ ] Live: `curl -s localhost:8000/api/runs/latest` shows a finished run capped at 5, with every to-do item done or left for a handler, and the summary
- [ ] Live, in the browser: queue page snapshots taken during the run show the to-do list filling in and items being ticked off, and the summary at the end
- [ ] Live, in the browser: each of the five claim pages shows the claim agent's steps and at least one section under "What the agent read"
- [ ] Live: every approval over $1,000 is waiting for sign-off with no payment, and every other approval is paid exactly its payout
- [ ] `docs/SPEC.md` describes the queue run, the to-do list, looking things up in the manual and the claims left for a handler. `docs/TECH_STACK.md` describes the two agents, their middleware and the model. `docs/STATUS.md` describes what's built, how to run it, and this live run with its time and decisions
- [ ] `npm run check` passes

## Not in this plan

- Working claims in parallel. The queue agent works one claim at a time.
- Surviving the process itself being stopped, such as closing the terminal mid-claim. That claim stays in progress, as in the pilot.
- Recording the queue agent's own steps. Its to-do list and summary are kept on the run, and each claim's steps are kept on the claim.
- A handler working a claim left for a handler from the dashboard. The claim is shown with its failures, and nothing more.
- Starting a run from the dashboard.
- Scoring the agent against `data/evals/`, which stays closed.
