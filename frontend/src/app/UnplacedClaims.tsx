import type { Claim } from "../contract";
import { VERDICT_STYLE, selectedClaimBackground } from "../tokens";

export function UnplacedClaims({
  claims,
  selectedClaimId,
  onSelect,
}: {
  claims: Claim[];
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
            <span className="claim-chip-warning"> ⚠ position doesn't fit the supplied text</span>
          </button>
        );
      })}
    </div>
  );
}
