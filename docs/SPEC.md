# The claims pilot

From the head of claims operations at UnderCover Travel Insurance.

## How claims work today

UnderCover sells travel insurance on three plans: Economy, Premium and First. Our three claims handlers work through a queue of claims by hand. For each claim, a handler reads the customer's story and documents and checks them against the policy and our policy wording. Then they approve the claim with a payout, decline it or refer it. A claim is referred when it needs someone's judgment or more information, as the claims manual explains.

## The pilot

We want an AI agent, the UnderCover Agent, to work the queue the way a handler does. For each claim it should:

- read the claim and the customer's policy and claim history
- look up the sections of the policy wording and the claims manual that the claim needs, the way a handler would, rather than being handed whole documents
- approve, decline or refer the claim
- work out the payout when it approves
- explain the decision in two or three sentences, along with the relevant section of the policy

Our goal is to handle claims straight through, as accurately as our handlers do.

## Working the queue

The agent organizes its own work. We start it once and it works every waiting claim, choosing the order itself, then finishes with a short summary for the handlers. For trials we can cap a run at a number of claims, leaving the rest waiting, and we can run it on one named claim.

- It plans the run as a to-do list and keeps it up to date, with each item to do, in progress, done or left for a handler.
- It hands each claim to a helper, a claim agent that works that one claim from a clean start and reports back in a line: the decision and payout, or what went wrong. Every step on a claim is recorded on that claim.
- Problems are put right without anyone stepping in. One bad claim never stops the run or leaves a claim stuck in progress. A claim that fails before it is decided goes back in the queue to be tried again, and a claim that fails twice is left for a handler. Before it finishes, the agent checks that it has not missed a waiting claim within its cap.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, decided or left for a handler.
- The agent's to-do list for the current run, and its summary when the run finishes.
- Each claim in full, with the agent's decision and its reasons.
- What the agent is doing on a claim while it works, step by step, which sections of the wording and the manual it read, and any try that failed.
- The agent's instructions for running the queue and for working a claim, read only. They are written from the policy wording and the claims manual, never from our handlers' decisions.

## Rules

- A payout over $1,000 needs a handler's sign-off. The agent can approve such a claim, but the payment waits until a handler signs off. The system must block the payment until then, even if the agent tries to pay.
- No claim is ever decided or paid twice.
- Decisions follow the policy wording, which always comes first, and the claims manual, which covers what the wording leaves open, such as a third claim within 12 months, losses to wild animals and meals without receipts.
- Our handlers' own decisions on these claims are in `data/evals/`. We use them to check the agent's work. The agent must never see them.
- Amounts are in US dollars.

## Our records

Everything is in `data/`, described in `data/README.md`: the claims queue, the policies, the customers, the plans, the handlers, the policy wording and the claims manual. The held-out claims in `data/evals/` are for checking the agent later and stay out of the queue.

## Not for now

- No sign-in. Everyone who uses the screens sees everything.
- No real payments.
- No messages to customers.