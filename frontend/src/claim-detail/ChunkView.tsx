import type { AuditRequest, Chunk } from "../contract";
import { codePointLength, sliceCodePoints } from "../contract";
import { ROLE_STYLE } from "../tokens";
import { partsForTurn } from "./excerptModel";
import type { ExcerptView } from "./excerptModel";

interface Props {
  chunk: Chunk;
  request: AuditRequest;
  views: Map<string, ExcerptView>;
  /** Evidence ids cited by the active concern; null = no active concern. */
  activeIds: Set<string> | null;
}

export function ChunkView({ chunk, request, views, activeIds }: Props) {
  return (
    <div className="cd-chunk">
      {chunk.rows.map((row) => {
        const turn = request.transcript[row.turn];
        const covering = row.highlights
          .map((h) => views.get(h.excerptId)!)
          .sort((a, b) => a.order - b.order);
        const length = codePointLength(turn.text);
        const parts = partsForTurn(
          length,
          covering.map((v) => v.ranges.get(row.turn)!),
        );
        const isContext = covering.length === 0;
        const cited = covering.some((v) => activeIds?.has(v.ev.id));
        const state = isContext || !activeIds ? "" : cited ? " emphasised" : " dimmed";
        const border = isContext ? undefined : ROLE_STYLE[covering[0].ev.role].color;
        return (
          <div key={row.turn}>
            <div
              className={`cd-row${isContext ? " context" : ""}${state}`}
              data-turn={row.turn}
              style={border ? { borderLeftColor: border } : undefined}
            >
              <div className="cd-row-head">
                <span>
                  {turn.speaker ?? "Unknown speaker"}
                  {turn.role ? ` · ${turn.role}` : ""}
                </span>
                <span>{turn.timestamp ?? `#${row.turn}`}</span>
              </div>
              <div className="cd-row-body">
                {length === 0 ? (
                  <em>(empty turn)</em>
                ) : (
                  parts.map((p) => (
                    <span key={p.from} className={`cd-${p.kind}`}>
                      {sliceCodePoints(turn.text, p.from, p.to)}
                    </span>
                  ))
                )}
              </div>
              {covering
                .filter((v) => v.firstTurn === row.turn)
                .map((v) => (
                  <span
                    key={v.ev.id}
                    className="cd-chip"
                    style={{ color: ROLE_STYLE[v.ev.role].color, borderColor: ROLE_STYLE[v.ev.role].color }}
                  >
                    {ROLE_STYLE[v.ev.role].label}
                  </span>
                ))}
            </div>
            {covering
              .filter((v) => v.lastTurn === row.turn && v.ev.note)
              .map((v) => (
                <p key={v.ev.id} className={`cd-note${state}`}>
                  <em>Audit note (paraphrase, not a quote): {v.ev.note}</em>
                </p>
              ))}
          </div>
        );
      })}
    </div>
  );
}
