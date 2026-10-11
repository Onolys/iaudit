import { useState } from "react";
import type { AuditRequest, Claim, ClaimCheck } from "../contract";
import { orderEvidence } from "../contract";
import { ExcerptList } from "./ExcerptList";
import { ConcernList } from "./ConcernList";
import { SuggestionBox } from "./SuggestionBox";
import { VerdictBadge } from "./VerdictBadge";
import "./claimDetail.css";

export interface ClaimDetailProps {
  claim: Claim;
  request: AuditRequest;
  check: ClaimCheck;
}

/** Remounts per claim so the active concern and expansion never leak between claims. */
export function ClaimDetail(props: ClaimDetailProps) {
  return <ClaimDetailBody key={props.claim.id} {...props} />;
}

function ClaimDetailBody({ claim, request, check }: ClaimDetailProps) {
  const [activeConcern, setActiveConcern] = useState<number | null>(null);
  const { placed, unplaceable } = orderEvidence(request, claim, check);
  const placedIds = new Set(placed.map((e) => e.id));
  const active = activeConcern === null ? undefined : claim.concerns[activeConcern];
  const activeIds = active ? new Set(active.evidence_ids) : null;

  return (
    <article className="cd-root" data-claim-id={claim.id}>
      <header>
        <VerdictBadge verdict={claim.verdict} />
        <p className="cd-explanation">{claim.explanation}</p>
        {claim.verdict === "insufficient_evidence" && (
          <p className="cd-note-line">
            Not substantiated by the supplied interview. This is not the same as contradicted.
          </p>
        )}
        {check.spanOutOfRange && (
          <p className="cd-warning" role="alert">
            A position returned for this claim does not fit the supplied input. Affected text is
            withheld; other content is unchanged.
          </p>
        )}
      </header>
      {typeof claim.suggested_revision === "string" && (
        <SuggestionBox text={claim.suggested_revision} />
      )}
      <ConcernList
        concerns={claim.concerns}
        placedIds={placedIds}
        activeIndex={activeConcern}
        onToggle={(i) => setActiveConcern((cur) => (cur === i ? null : i))}
      />
      <ExcerptList request={request} placed={placed} unplaceable={unplaceable} activeIds={activeIds} />
    </article>
  );
}
