import type { Verdict } from "../contract";
import { VERDICT_STYLE } from "../tokens";

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const { icon, label, color } = VERDICT_STYLE[verdict];
  return (
    <span className="cd-badge" data-verdict={verdict} style={{ color, borderColor: color }}>
      <span aria-hidden="true">{icon}</span> <span>{label}</span>
    </span>
  );
}
