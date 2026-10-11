import type { Claim, ClaimCheck } from "../contract";
import { VERDICT_STYLE, selectedClaimBackground } from "../tokens";

export function UnplacedClaims({
  claims,
  checks,
  selectedClaimId,
  onSelect,
}: {
  claims: Claim[];
  checks: Record<string, ClaimCheck>;
  selectedClaimId: string | null;
  onSelect: (id: string) => void;
}) {
  if (claims.length === 0) return null;
  return (
    <div className="unplaced-claims">
      <h4>Unplaced claims</h4>
      {claims.map((c) => {
        const style = VERDICT_STYLE[c.verdict];
        const selected = c.id === selectedClaimId;
        return (
          <button
            key={c.id}
            type="button"
            className={selected ? "claim-chip selected" : "claim-chip"}
            data-claim-id={c.id}
            style={{ color: style.color, backgroundColor: selected ? selectedClaimBackground : undefined }}
            onClick={() => onSelect(c.id)}
          >
            <span aria-hidden="true">{style.icon}</span> {style.label} · {c.id}
            <span className="claim-chip-warning">
              {checks[c.id]?.claimSpanOk ? " ⚠ overlaps another claim, so it can't be highlighted" : " ⚠ position doesn't fit the supplied text"}
            </span>
          </button>
        );
      })}
    </div>
  );
}
