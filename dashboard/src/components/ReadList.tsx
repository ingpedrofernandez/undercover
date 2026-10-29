import type { Step } from "../api";
import { firstLine } from "../format";

// A read step's first line names the section the agent read.
export function ReadList({ steps }: Readonly<{ steps: Step[] }>) {
  const sections = [
    ...new Set(
      steps.filter((s) => s.kind === "read").map((s) => firstLine(s.content)),
    ),
  ];
  return (
    <section className="panel" aria-labelledby="reads-title">
      <h2 id="reads-title">What the agent read</h2>
      {sections.length === 0 ? (
        <p className="muted">
          Nothing yet. The sections of the policy wording and the claims manual
          the agent reads appear here.
        </p>
      ) : (
        <ul className="reads">
          {sections.map((section) => (
            <li key={section}>{section}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
