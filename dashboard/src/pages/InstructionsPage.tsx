import { api } from "../api";
import { Message } from "../components/Message";
import { useLoad } from "../useLoad";

export function InstructionsPage() {
  const { data, error } = useLoad(api.getInstructions);

  return (
    <>
      <h1>Agent instructions</h1>
      <p className="lead">
        What the agent reads before it works a claim. It looks up the policy
        wording and the claims manual section by section as it needs them. This
        page is read only.
      </p>
      <section className="panel">
        {data ? (
          <pre className="instructions">{data.claim}</pre>
        ) : (
          <Message error={error} />
        )}
      </section>
    </>
  );
}
