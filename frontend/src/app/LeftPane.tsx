import type { ReactNode } from "react";
import type { AuditRequest, AuditResponse, Claim, ResponseAnalysis, Verdict } from "../contract";
import { notProcessedSections } from "../contract";
import type { ReviewState } from "./reviewState";
import { ClaimText } from "./ClaimText";
import { SectionCard } from "./SectionCard";
import { UnplacedClaims } from "./UnplacedClaims";

interface LeftPaneProps {
  request: AuditRequest;
  response: AuditResponse;
  analysis: ResponseAnalysis;
  state: ReviewState;
  onSelect: (id: string) => void;
  onNavigate: (verdict: Verdict, scope: number) => void;
}

export function LeftPane({ request, response, analysis, state, onSelect, onNavigate }: LeftPaneProps) {
  const notProcessed = notProcessedSections(response);
  const sectionCount = request.assessment.length;
  const unplaced = analysis.orderedClaims.filter((c) => !analysis.checks[c.id].claimSpanOk);
  const inSection = (i: number) => unplaced.filter((c) => c.span.start.index === i);
  const outside: Claim[] = unplaced.filter((c) => !Number.isInteger(c.span.start.index) || c.span.start.index < 0 || c.span.start.index >= sectionCount);
  const selectedClaimId = state.selectedClaimId;

  const cards: ReactNode[] = request.assessment.map((section, i) => (
    <SectionCard
      key={i}
      label={section.label || `Section ${i + 1}`}
      score={section.score}
      notProcessed={notProcessed.has(i)}
      counts={analysis.counts.bySection[i]}
      activeVerdict={state.nav?.scope === i ? state.nav.verdict : null}
      onPick={(verdict) => onNavigate(verdict, i)}
    >
      <ClaimText
        request={request}
        sectionIndex={i}
        checks={analysis.checks}
        claims={analysis.orderedClaims}
        selectedClaimId={selectedClaimId}
        onSelect={onSelect}
      />
      <UnplacedClaims claims={inSection(i)} selectedClaimId={selectedClaimId} onSelect={onSelect} />
    </SectionCard>
  ));
  if (outside.length > 0) {
    cards.push(
      <SectionCard key="outside" label="Claims outside the supplied assessment">
        <UnplacedClaims claims={outside} selectedClaimId={selectedClaimId} onSelect={onSelect} />
      </SectionCard>,
    );
  }
  return <div className="left-pane">{cards}</div>;
}
