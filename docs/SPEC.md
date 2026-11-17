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

Claims arrive in batches, so the agent works many at once. A handler starts a dispatch on the queue page and chooses how many claim agents work at the same time, from 1 to 25. A dispatch carries on every claim left in progress and works every waiting claim, oldest submitted first. Choosing the claims is a fixed rule, so code does it, with no model. Only one dispatch or evaluation runs at a time, and a second start is refused while one is running. We can also run the agent on one named claim.

- Each claim is worked by a claim agent from a clean start, as a handler would, and every step on a claim is recorded on that claim.
- Problems are put right without anyone stepping in. A claim that hits a rate limit or a timeout waits and carries on from where it got to, as the same try, and one still hitting them after its waits stays in progress for the next dispatch. A claim that fails with any other error goes back in the queue and the same dispatch tries it once more, and a claim that fails twice is left for a handler. One bad claim never stops a dispatch.
- A payout that needs a handler's sign-off waits for one. The claim agent stops at that point and keeps its place. As soon as a handler signs off on the dashboard, the agent picks the claim back up and pays it, and the claim page shows who signed off and when.
- Every step on a claim is saved as it happens. If the agent is stopped partway, by a crash or a restart, the dispatch shows as stopped, and the next dispatch carries each claim it left in progress on from where it stopped, as the same try rather than a new one.
- When a dispatch finishes, it is summed up from our records, with no model writing it: how many claims were approved, declined and referred, each payout waiting for a sign-off, and each claim left for a handler or still in progress.
- The tokens and cost of every model call, and the time the agent spends on each claim, leaving out any wait for a sign-off, are recorded with the dispatch or evaluation they happened in.

## Checking the agent's work

On the Scoreboard a handler runs an evaluation: the agent works copies of one of our two labelled sets, whole or just its five tiny claims, with the same claim agents as a dispatch. The copies never show in the queue, a dispatch never carries them on, and nobody signs them off, so a held approval counts as finished. Each evaluation is scored against our handlers' decisions from our own records: how often the decision matches, how often the payout is right too, what the mistakes would cost, how many claims go straight through, and the model cost and time per claim.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, decided or left for a handler.
- The latest dispatch: each of its claims and where it stands, its model cost and time, and its summary when it finishes.
- Each claim in full, with the agent's decision and its reasons.
- What the agent is doing on a claim while it works, step by step, which sections of the wording and the manual it read, and any try that failed.
- The scoreboard: every evaluation with its measures, and each one's claims with our handler's decision beside the agent's, the misses easy to spot.
- The claim agent's instructions, read only. They are written from the policy wording and the claims manual, never from our handlers' decisions.

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