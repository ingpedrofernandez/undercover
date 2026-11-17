import { api, type Dispatch } from "../api";
import { time } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";
import { Message } from "./Message";

export function RunPanel() {
  const { data: dispatch, error } = useLoad(api.getLatestDispatch, REFRESH_MS);

  return (
    <section className="panel run" aria-labelledby="run-title">
      <h2 id="run-title">Dispatch</h2>
      {dispatch === undefined && <Message error={error} />}
      {dispatch === null && <p className="muted">No dispatch yet.</p>}
      {dispatch && <DispatchLine dispatch={dispatch} />}
    </section>
  );
}

function stateOf(dispatch: Dispatch): string {
  if (dispatch.status === "running") return "Running now.";
  if (dispatch.status === "stopped") return "Stopped before it finished.";
  return `Finished at ${time(dispatch.finished_at ?? dispatch.started_at)}.`;
}

function DispatchLine({ dispatch }: Readonly<{ dispatch: Dispatch }>) {
  const agents = dispatch.agents === 1 ? "claim agent" : "claim agents";
  return (
    <p className="muted small">
      Dispatch {dispatch.run_id}, {dispatch.agents} {agents} at once, started at{" "}
      {time(dispatch.started_at)}. {stateOf(dispatch)}
    </p>
  );
}
