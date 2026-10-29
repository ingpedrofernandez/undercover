import { api } from "../api";
import { Message } from "../components/Message";
import { useLoad } from "../useLoad";

export function InstructionsPage() {
  const { data, error } = useLoad(api.getInstructions);

  return (
    <>
      <h1>Agent instructions</h1>
      <p className="lead">
        The agent runs the queue with the first set of instructions, and hands
        each claim to a claim agent that follows the second. The claim agent
        looks up the policy wording and the claims manual section by section as
        it needs them. This page is read only.
      </p>
      {data ? (
        <div className="column">
          <section className="panel" aria-labelledby="queue-title">
            <h2 id="queue-title">Running the queue</h2>
            <pre className="instructions">{data.queue}</pre>
          </section>
          <section className="panel" aria-labelledby="claim-title">
            <h2 id="claim-title">Working a claim</h2>
            <pre className="instructions">{data.claim}</pre>
          </section>
        </div>
      ) : (
        <section className="panel">
          <Message error={error} />
        </section>
      )}
    </>
  );
}
