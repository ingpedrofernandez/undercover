import type { Claim, Status } from "../api";
import { money, time } from "../format";
import { DecisionChip } from "./Chips";
import { SignOffForm } from "./SignOffForm";

// What the panel says about a claim that has no decision yet.
function progress(status: Status): string {
  if (status === "in_progress") return "The agent is working on this claim.";
  if (status === "left_for_handler")
    return "The agent couldn't finish this claim after two tries, so it's left for a handler.";
  return "The agent hasn't started on this claim.";
}

// When a held payout was signed off, if the record says.
function at(signedOffAt: string | null): string {
  return signedOffAt ? ` at ${time(signedOffAt)}` : "";
}

// A payout held for sign-off: the form, or a note on an evaluation's copy,
// which nobody signs off.
function Held({
  claim,
  payout,
  onSignedOff,
}: Readonly<{ claim: Claim; payout: number; onSignedOff: () => void }>) {
  if (claim.evaluation_id !== null)
    return (
      <p className="muted">
        Held for sign-off. An evaluation's copy is never signed off.
      </p>
    );
  return (
    <div className="sign-off">
      <p>
        The payment of <span className="mono">{money(payout)}</span> is over the
        approval limit and waits for a handler's sign-off.
      </p>
      <SignOffForm claimId={claim.claim_id} onSignedOff={onSignedOff} />
    </div>
  );
}

export function DecisionPanel({
  claim,
  onSignedOff,
}: Readonly<{ claim: Claim; onSignedOff: () => void }>) {
  const { decision, payment } = claim;

  return (
    <section className="panel" aria-labelledby="decision-title">
      <h2 id="decision-title">Decision</h2>
      {!decision && <p className="muted">{progress(claim.status)}</p>}
      {decision && (
        <>
          <div className="decision-line">
            <DecisionChip decision={decision.decision} />
            {decision.decision === "approve" && (
              <span className="payout mono">{money(decision.payout)}</span>
            )}
          </div>
          <p className="section-ref">{decision.section}</p>
          <p className="reason">{decision.reason}</p>
          <p className="small muted">Decided at {time(decision.decided_at)}</p>
        </>
      )}
      {decision?.signed_off_by && !payment && (
        <p className="payment">
          Signed off by {decision.signed_off_by}
          {at(decision.signed_off_at)}
        </p>
      )}
      {decision?.decision === "approve" &&
        !payment &&
        claim.status === "in_progress" && (
          <p className="muted">The agent is paying this claim.</p>
        )}
      {payment && (
        <p className="payment">
          Paid <span className="mono">{money(payment.amount)}</span>
          {payment.signed_off_by &&
            `, signed off by ${payment.signed_off_by}${at(payment.signed_off_at)}`}
        </p>
      )}
      {decision && claim.status === "waiting_for_sign_off" && (
        <Held
          claim={claim}
          payout={decision.payout}
          onSignedOff={onSignedOff}
        />
      )}
    </section>
  );
}
