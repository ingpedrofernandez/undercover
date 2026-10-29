import { api, type Run } from "../api";
import { time, todoLabels } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";
import { Message } from "./Message";

export function RunPanel() {
  const { data: run, error } = useLoad(api.getLatestRun, REFRESH_MS);

  return (
    <section className="panel run" aria-labelledby="run-title">
      <h2 id="run-title">The agent's to-do list</h2>
      {run === undefined && <Message error={error} />}
      {run === null && (
        <p className="muted">The agent hasn't worked the queue yet.</p>
      )}
      {run && <RunDetails run={run} />}
    </section>
  );
}

function RunDetails({ run }: Readonly<{ run: Run }>) {
  const claims = run.limit === 1 ? "claim" : "claims";
  return (
    <>
      <p className="muted small">
        Run {run.run_id}, started at {time(run.started_at)}, capped at{" "}
        {run.limit} {claims}.{" "}
        {run.finished_at
          ? `Finished at ${time(run.finished_at)}.`
          : "Running now."}
      </p>
      {run.todos.length === 0 ? (
        <p className="muted">No items yet.</p>
      ) : (
        <ol className="todos">
          {run.todos.map((todo) => (
            <li key={todo.content} className="todo">
              <span className={`chip todo-${todo.status}`}>
                {todoLabels[todo.status]}
              </span>
              <span>{todo.content}</span>
            </li>
          ))}
        </ol>
      )}
      {run.summary && (
        <>
          <h3>Summary</h3>
          <p className="summary">{run.summary}</p>
        </>
      )}
    </>
  );
}
