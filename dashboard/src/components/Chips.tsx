import type { DecisionKind, RunStatus, Status } from "../api";
import { decisionLabels, runStatusLabels, statusLabels } from "../format";

export function StatusChip({ status }: Readonly<{ status: Status }>) {
  return (
    <span className={`chip status-${status}`}>{statusLabels[status]}</span>
  );
}

export function RunStatusChip({ status }: Readonly<{ status: RunStatus }>) {
  return (
    <span className={`chip run-${status}`}>{runStatusLabels[status]}</span>
  );
}

export function DecisionChip({
  decision,
}: Readonly<{ decision: DecisionKind }>) {
  return (
    <span className={`chip decision-${decision}`}>
      {decisionLabels[decision]}
    </span>
  );
}
