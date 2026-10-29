# Tech stack

- `backend/`: FastAPI and SQLite. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount. The backend enforces the claim states, the sign-off limit and the two tries on a claim, so the rules hold whatever an agent does.
- `agent/`: two agents built with LangChain's `create_agent` on OpenRouter, with no other agent framework. The queue agent plans a run as a to-do list and hands each claim to the claim agent, which works one claim from a clean start. LangChain's `ModelRetryMiddleware` and `ModelCallLimitMiddleware` retry failed model calls and stop an agent that goes round in circles, and our own middleware sends the queue agent back if it tries to finish with a waiting claim missed. The agents reach claims, runs, their instructions, the policy wording and the claims manual only through the backend's API. It uses DeepSeek V4.1 Flash (`deepseek/deepseek-v4.1-flash`) with low reasoning effort by default, or the model in the environment variable `MODEL_NAME` if set, such as `openrouter/free`.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.
