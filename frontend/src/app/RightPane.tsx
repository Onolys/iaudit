import type { AuditRequest, ResponseAnalysis } from "../contract";
import { ClaimDetail } from "../claim-detail/ClaimDetail";
import type { ReviewState } from "./reviewState";

interface RightPaneProps {
  request: AuditRequest;
  analysis: ResponseAnalysis;
  state: ReviewState;
  onStep: (delta: 1 | -1) => void;
}

export function RightPane({ request, analysis, state, onStep }: RightPaneProps) {
  const claim = analysis.orderedClaims.find((c) => c.id === state.selectedClaimId);
  const { nav } = state;
  return (
    <div className="right-pane">
      {nav ? (
        <div className="nav-stepper">
          <button type="button" aria-label="Previous claim" disabled={nav.position === 0} onClick={() => onStep(-1)}>
            ‹
          </button>
          <span>
            {nav.position + 1} of {nav.claimIds.length}
          </span>
          <button
            type="button"
            aria-label="Next claim"
            disabled={nav.position === nav.claimIds.length - 1}
            onClick={() => onStep(1)}
          >
            ›
          </button>
        </div>
      ) : null}
      {claim ? (
        <ClaimDetail key={claim.id} claim={claim} request={request} check={analysis.checks[claim.id]} />
      ) : (
        <p className="app-message">
          {analysis.orderedClaims.length === 0 ? "This audit contains no claims." : "No claim selected."}
        </p>
      )}
    </div>
  );
}
