import { useState } from "react";
import { Link } from "react-router";
import { api, type EvalSet, type EvaluationSummary } from "../api";
import { AgentsForm } from "../components/AgentsForm";
import { Message } from "../components/Message";
import {
  measureColumns,
  runStatusLabels,
  setLabels,
  setName,
  time,
} from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";

export function ScoreboardPage() {
  const { data: evaluations, error } = useLoad(api.listEvaluations, REFRESH_MS);
  const [evalSet, setEvalSet] = useState<EvalSet>("evaluation");
  const [tiny, setTiny] = useState(false);

  return (
    <>
      <h1>Scoreboard</h1>
      <p className="lead">
        An evaluation works copies of one of our labelled sets with the same
        claim agents as a dispatch, and scores them against our handlers'
        decisions. The copies never show in the queue.
      </p>
      <AgentsForm
        action="Start an evaluation"
        started="Evaluation started"
        onStart={(agents) => api.startEvaluation(agents, evalSet, tiny)}
      >
        <label>
          Set
          <select
            value={evalSet}
            onChange={(event) => {
              setEvalSet(event.target.value as EvalSet);
            }}
          >
            <option value="evaluation">{setLabels.evaluation}</option>
            <option value="held_out">{setLabels.held_out}</option>
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={tiny}
            onChange={(event) => {
              setTiny(event.target.checked);
            }}
          />
          Just the five tiny claims
        </label>
      </AgentsForm>
      <section className="panel table-scroll" aria-label="Evaluations">
        {evaluations === undefined && <Message error={error} />}
        {evaluations?.length === 0 && (
          <p className="muted">No evaluations yet.</p>
        )}
        {evaluations && evaluations.length > 0 && (
          <EvaluationsTable evaluations={evaluations} />
        )}
      </section>
    </>
  );
}

function EvaluationsTable({
  evaluations,
}: Readonly<{ evaluations: EvaluationSummary[] }>) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Evaluation</th>
          <th>Started</th>
          <th>Set</th>
          <th className="num">Agents</th>
          <th>Model</th>
          <th>State</th>
          <th className="num">Claims</th>
          {measureColumns.map(([heading]) => (
            <th className="num" key={heading}>
              {heading}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {evaluations.map((evaluation) => (
          <tr key={evaluation.run_id}>
            <td>
              <Link to={`/evaluations/${String(evaluation.run_id)}`}>
                Evaluation {evaluation.run_id}
              </Link>
            </td>
            <td className="nowrap">{time(evaluation.started_at)}</td>
            <td className="nowrap">{setName(evaluation)}</td>
            <td className="num mono">{evaluation.agents}</td>
            <td className="nowrap">
              {evaluation.model} ({evaluation.reasoning_effort})
            </td>
            <td>{runStatusLabels[evaluation.status]}</td>
            <td className="num mono">{evaluation.claim_count}</td>
            {measureColumns.map(([heading, value]) => (
              <td className="num mono" key={heading}>
                {value(evaluation.measures)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
