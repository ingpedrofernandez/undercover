# Code standards

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: a short README and no emojis.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.

## Structure

Passing tests and a clean lint do not make code fit for a PR. Hold every change to these too.

7. One module, one job. A module never reaches into another to borrow its helpers. When two modules need the same thing, it moves to a module of its own that both import.
8. One way to do each thing. Every call to the backend goes through one client: `agent/api.py`, `dashboard/src/api.ts` or `e2e/api.ts`. None of the backend's API paths, nor its base URL, is written anywhere else.
9. Backend: `main.py` creates the app, and each area of the API is a router in its own module.
10. Agent: five parts. Every tool is in `agent/tools.py`. The harness (the model, the claim graph and its nodes, the checkpointer, tracing, and `work_claim`, the one function that works a claim with the claim agent) is in `agent/harness.py`. The dispatcher, a LangGraph graph with no model that works a run's claims with up to N claim agents at once, is in `agent/dispatcher.py`, and reaches the claim agent only through `harness.work_claim`. The UnderCover work done with them, dispatches and evaluations from start to finish, is in `agent/work.py`. `agent/service.py` is the agent's web service, which hands each request on and does no work itself. A graph's nodes and a tool get what a run knows through the framework's runtime context (`context_schema`, `Runtime` and `ToolRuntime`), not through closures.
11. Use what the framework already has (LangChain middleware, runtime context, React state) before writing your own. Check the library's current API first.
12. Agent instructions give a goal, what a good result looks like and the limits to respect. They are not step-by-step scripts: if the steps are fixed, they belong in code.
13. Before extending code, check it meets these standards. If it doesn't, fix it first rather than building on it.
