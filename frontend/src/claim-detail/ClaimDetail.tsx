import { useState } from "react";
import type { AuditRequest, Claim, ClaimCheck, Evidence } from "../contract";
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

/** Duplicate evidence ids are tolerated by ignoring all but the first occurrence. */
const firstPerId = (list: Evidence[]): Evidence[] =>
  list.filter((e, i) => list.findIndex((o) => o.id === e.id) === i);

/** Remounts per claim so the active concern and expansion never leak between claims. */
export function ClaimDetail(props: ClaimDetailProps) {
  return <ClaimDetailBody key={props.claim.id} {...props} />;
}

function ClaimDetailBody({ claim, request, check }: ClaimDetailProps) {
  const [activeConcern, setActiveConcern] = useState<number | null>(null);
  const ordered = orderEvidence(request, claim, check);
  const placed = firstPerId(ordered.placed);
  const unplaceable = firstPerId(ordered.unplaceable);
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
      {claim.verdict === "out_of_scope" ? (
        claim.out_of_scope_reason && (
          <section className="cd-oos" aria-label="Out of scope reason">
            <h3>Why this is out of scope</h3>
            <p>{claim.out_of_scope_reason}</p>
          </section>
        )
      ) : (
        <>
          <ConcernList
            concerns={claim.concerns}
            placedIds={placedIds}
            activeIndex={activeConcern}
            onToggle={(i) => setActiveConcern((cur) => (cur === i ? null : i))}
          />
          <ExcerptList
            request={request}
            placed={placed}
            unplaceable={unplaceable}
            verdict={claim.verdict}
            evidenceCount={claim.evidence.length}
            activeIds={activeIds}
          />
        </>
      )}
    </article>
  );
}
