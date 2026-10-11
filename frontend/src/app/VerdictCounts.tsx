import { VERDICTS } from "../contract";
import type { VerdictCounts as Counts, Verdict } from "../contract";
import { VERDICT_STYLE } from "../tokens";

export function VerdictCounts({
  counts,
  active,
  onPick,
  disabled = false,
}: {
  counts: Counts;
  active: Verdict | null;
  onPick: (verdict: Verdict) => void;
  disabled?: boolean;
}) {
  return (
    <div className="verdict-counts">
      {VERDICTS.map((verdict) => {
        const style = VERDICT_STYLE[verdict];
        const count = counts[verdict] ?? 0;
        return (
          <button
            key={verdict}
            type="button"
            className="verdict-count"
            style={{ color: style.color }}
            aria-pressed={active === verdict}
            disabled={disabled || count === 0}
            onClick={() => onPick(verdict)}
          >
            <span aria-hidden="true">{style.icon}</span>
            <span>{style.label}</span>
            <strong>{count}</strong>
          </button>
        );
      })}
    </div>
  );
}
