import { type ReactNode, type SyntheticEvent, useState } from "react";

// Starts a run with N claim agents at once, from 1 to 25, and says whether it
// started. Any other choices for the run go in children.
export function AgentsForm({
  action,
  started,
  onStart,
  children,
}: Readonly<{
  action: string;
  started: string;
  onStart: (agents: number) => Promise<unknown>;
  children?: ReactNode;
}>) {
  const [agents, setAgents] = useState(3);
  const [note, setNote] = useState<string>();
  const [error, setError] = useState<string>();
  const [sending, setSending] = useState(false);

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSending(true);
    setNote(undefined);
    setError(undefined);
    onStart(agents)
      .then(
        () => {
          setNote(started);
        },
        (reason: unknown) => {
          setError(reason instanceof Error ? reason.message : "Start failed");
        },
      )
      .finally(() => {
        setSending(false);
      });
  }

  return (
    <form className="panel start-form" onSubmit={submit} aria-label={action}>
      {children}
      <label>
        Claim agents at once
        <input
          type="number"
          min={1}
          max={25}
          required
          value={agents}
          onChange={(event) => {
            setAgents(Number(event.target.value));
          }}
        />
      </label>
      <button type="submit" disabled={sending}>
        {action}
      </button>
      {note && (
        <p className="form-note muted" role="status">
          {note}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
