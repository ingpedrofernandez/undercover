import { api } from "../api";
import { Message } from "../components/Message";
import { useLoad } from "../useLoad";

export function InstructionsPage() {
  const { data, error } = useLoad(api.getInstructions);

  return (
    <>
      <h1>Agent instructions</h1>
      <p className="lead">
        A dispatch hands each claim to a claim agent that follows these
        instructions. The claim agent looks up the policy wording and the claims
        manual section by section as it needs them. This page is read only.
      </p>
      <section className="panel" aria-labelledby="claim-title">
        <h2 id="claim-title">Working a claim</h2>
        {data ? (
          <pre className="instructions">{data.claim}</pre>
        ) : (
          <Message error={error} />
        )}
      </section>
    </>
  );
}
