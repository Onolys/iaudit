import type { AuditRequest, ClaimCheck, Claim } from "../contract";
import { segmentSection } from "../contract";
import { VERDICT_STYLE, selectedClaimBackground } from "../tokens";

interface ClaimTextProps {
  request: AuditRequest;
  sectionIndex: number;
  checks: Record<string, ClaimCheck>;
  claims: Claim[];
  selectedClaimId: string | null;
  onSelect: (id: string) => void;
}

/** Pieces are adjacent children so `textContent` equals the supplied section text. */
export function ClaimText({ request, sectionIndex, checks, claims, selectedClaimId, onSelect }: ClaimTextProps) {
  const verdictOf = new Map(claims.map((c) => [c.id, c.verdict]));
  const pieces = segmentSection(request, sectionIndex, checks, claims);
  return (
    <p className="section-text">
      {pieces.map((piece, i) => {
        const claimId = piece.claimId;
        if (piece.kind === "plain" || claimId === undefined) return piece.text;
        const style = VERDICT_STYLE[verdictOf.get(claimId)!];
        const selected = claimId === selectedClaimId;
        return (
          <span
            key={i}
            role="button"
            tabIndex={0}
            className={selected ? "claim-span selected" : "claim-span"}
            data-claim-id={claimId}
            title={style.label}
            style={{
              textDecorationColor: style.color,
              textDecorationStyle: style.underline,
              backgroundColor: selected ? selectedClaimBackground : undefined,
            }}
            onClick={() => onSelect(claimId)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(claimId);
              }
            }}
          >
            {piece.text}
          </span>
        );
      })}
    </p>
  );
}
