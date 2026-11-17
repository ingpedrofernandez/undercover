import { useCallback } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, type Evaluation, type ScoredClaim } from "../api";
import { DecisionChip } from "../components/Chips";
import { Message } from "../components/Message";
import {
  cost,
  duration,
  measureColumns,
  money,
  runStatusLabels,
  setName,
  time,
} from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";

export function EvaluationPage() {
  const { runId = "" } = useParams();
  const load = useCallback(() => api.getEvaluation(Number(runId)), [runId]);
  const { data: evaluation, error } = useLoad(load, REFRESH_MS);

  if (!evaluation) {
    if (error instanceof ApiError && error.status === 404)
      return <p className="message">Evaluation not found</p>;
    return <Message error={error} />;
  }

  return (
    <>
      <h1>Evaluation {evaluation.run_id}</h1>
      <p className="lead">
        {setName(evaluation)}, {evaluation.agents} claim agents at once,{" "}
        {evaluation.model} ({evaluation.reasoning_effort}), started at{" "}
        {time(evaluation.started_at)}. {runStatusLabels[evaluation.status]}.
      </p>
      <MeasuresPanel evaluation={evaluation} />
      <section className="panel table-scroll" aria-label="Claims">
        <ClaimsTable claims={evaluation.claims} />
      </section>
    </>
  );
}

function MeasuresPanel({ evaluation }: Readonly<{ evaluation: Evaluation }>) {
  return (
    <section className="panel" aria-labelledby="measures-title">
      <h2 id="measures-title">Measures</h2>
      <dl className="facts">
        {measureColumns.map(([heading, value]) => (
          <div key={heading}>
            <dt>{heading}</dt>
            <dd className="mono">{value(evaluation.measures)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

// How the agent's answer on a claim compares with the handler's.
function result(claim: ScoredClaim): [string, string] {
  if (claim.right) return ["Right", "result-right"];
  if (claim.right_decision) return ["Wrong amount", "result-amount"];
  return ["Wrong decision", "result-decision"];
}

function Answer({
  decision,
  payout,
}: Readonly<{ decision: ScoredClaim["decision"]; payout: number | null }>) {
  if (decision === null)
    return <span className="muted">No decision (counts as a referral)</span>;
  return (
    <span className="nowrap">
      <DecisionChip decision={decision} />{" "}
      {decision === "approve" && payout !== null && (
        <span className="mono">{money(payout)}</span>
      )}
    </span>
  );
}

function ClaimsTable({ claims }: Readonly<{ claims: ScoredClaim[] }>) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Claim</th>
          <th>Copy of</th>
          <th>Result</th>
          <th>Handler</th>
          <th>Agent</th>
          <th className="reason-cell">Agent's reason</th>
          <th className="num">Cost of mistake</th>
          <th className="num">Time</th>
          <th className="num">Cost</th>
        </tr>
      </thead>
      <tbody>
        {claims.map((claim) => {
          const [label, kind] = result(claim);
          return (
            <tr key={claim.claim_id} className={claim.right ? "" : "miss"}>
              <td className="nowrap">
                <Link className="mono" to={`/claims/${claim.claim_id}`}>
                  {claim.claim_id}
                </Link>
              </td>
              <td className="mono nowrap">{claim.source_id}</td>
              <td>
                <span className={`chip ${kind}`}>{label}</span>
              </td>
              <td>
                <Answer
                  decision={claim.handler_decision}
                  payout={claim.handler_payout}
                />
              </td>
              <td>
                <Answer decision={claim.decision} payout={claim.payout} />
              </td>
              <td className="small reason-cell">{claim.reason}</td>
              <td className="num mono">{money(claim.mistake_cost)}</td>
              <td className="num mono">{duration(claim.seconds)}</td>
              <td className="num mono">{cost(claim.cost)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
