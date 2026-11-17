import { Link } from "react-router";
import {
  api,
  type Dispatch,
  type DispatchSummary,
  type RunClaim,
} from "../api";
import { cost, duration, money, time } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";
import { DecisionChip, StatusChip } from "./Chips";
import { Message } from "./Message";

export function RunPanel() {
  const { data: dispatch, error } = useLoad(api.getLatestDispatch, REFRESH_MS);

  return (
    <section className="panel run" aria-labelledby="run-title">
      <h2 id="run-title">Dispatch</h2>
      {dispatch === undefined && <Message error={error} />}
      {dispatch === null && <p className="muted">No dispatch yet.</p>}
      {dispatch && <DispatchDetails dispatch={dispatch} />}
    </section>
  );
}

function stateOf(dispatch: Dispatch): string {
  if (dispatch.status === "running") return "Running now.";
  if (dispatch.status === "stopped") return "Stopped before it finished.";
  const took = duration(dispatch.run_seconds ?? 0);
  return `Finished at ${time(dispatch.finished_at ?? dispatch.started_at)}, after ${took}.`;
}

function DispatchDetails({ dispatch }: Readonly<{ dispatch: Dispatch }>) {
  const agents = dispatch.agents === 1 ? "claim agent" : "claim agents";
  return (
    <>
      <p className="muted small">
        Dispatch {dispatch.run_id}, {dispatch.agents} {agents} at once,{" "}
        {dispatch.model} ({dispatch.reasoning_effort}), started at{" "}
        {time(dispatch.started_at)}. {stateOf(dispatch)}
      </p>
      <p className="small">
        Model cost {cost(dispatch.cost)}. The claims took{" "}
        {duration(dispatch.work_seconds)} of the agents' time in all.
      </p>
      {dispatch.claims.length === 0 ? (
        <p className="muted">No claims taken.</p>
      ) : (
        <ClaimsTable claims={dispatch.claims} />
      )}
      {dispatch.summary && (
        <>
          <h3>Summary</h3>
          <Summary summary={dispatch.summary} />
        </>
      )}
    </>
  );
}

function ClaimsTable({ claims }: Readonly<{ claims: RunClaim[] }>) {
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Claim</th>
            <th>State</th>
            <th>Decision</th>
            <th className="num">Payout</th>
            <th>Started</th>
            <th className="num">Time</th>
            <th className="num">Cost</th>
          </tr>
        </thead>
        <tbody>
          {claims.map((claim) => (
            <tr key={claim.claim_id}>
              <td className="nowrap">
                <Link className="mono" to={`/claims/${claim.claim_id}`}>
                  {claim.claim_id}
                </Link>
              </td>
              <td>
                <StatusChip status={claim.status} />
              </td>
              <td>
                {claim.decision && <DecisionChip decision={claim.decision} />}
              </td>
              <td className="num mono">
                {claim.payout !== null && money(claim.payout)}
              </td>
              <td className="nowrap">
                {claim.started_at && time(claim.started_at)}
              </td>
              <td className="num mono">{duration(claim.seconds)}</td>
              <td className="num mono">{cost(claim.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function listed(items: string[]): string {
  return items.length === 0 ? "none" : items.join(", ");
}

function Summary({ summary }: Readonly<{ summary: DispatchSummary }>) {
  const held = summary.waiting_for_sign_off.map(
    (payout) => `${payout.claim_id} (${money(payout.payout)})`,
  );
  return (
    <ul className="summary">
      <li>
        Approved {summary.approved}, declined {summary.declined} and referred{" "}
        {summary.referred}.
      </li>
      <li>Waiting for sign-off: {listed(held)}.</li>
      <li>Left for a handler: {listed(summary.left_for_handler)}.</li>
      <li>Still in progress: {listed(summary.in_progress)}.</li>
    </ul>
  );
}
