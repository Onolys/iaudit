/**
 * Transcript (PRD R4, D11): role labels, `start_ms` timestamps and highlight segments, rendered as
 * React text nodes only. The selected instance id drives scroll and a pulse highlight.
 */
import { useEffect, useMemo, useRef } from "react";
import type { components } from "../../api/schema";
import { formatElapsed } from "../../lib/format";
import { buildSegments, type SpanInput } from "../../lib/spans";

export type Turn = components["schemas"]["TranscriptTurn"];

/** A line to highlight: code-point offsets into `turn_id`'s text, with the quote the report claims. */
export interface Highlight extends SpanInput {
  turn_id: string;
}

export interface TranscriptProps {
  turns: Turn[];
  highlights: Highlight[];
  selectedId: string | null;
}

const ROLE_LABEL: Record<string, string> = { clinician: "Clinician", client: "Client" };
const label = (t: Turn) => (t.role ? (ROLE_LABEL[t.role] ?? t.role) : (t.speaker ?? "Unknown speaker"));

export function Transcript({ turns, highlights, selectedId }: TranscriptProps) {
  const root = useRef<HTMLOListElement>(null);

  const { rows, unplaced } = useMemo(() => {
    const byTurn = new Map<string, Highlight[]>();
    const known = new Set(turns.map((t) => t.id));
    const orphans: Highlight[] = [];
    for (const h of highlights) {
      if (!known.has(h.turn_id)) orphans.push(h);
      else byTurn.set(h.turn_id, [...(byTurn.get(h.turn_id) ?? []), h]);
    }
    const out = turns.map((t) => ({ turn: t, ...buildSegments(t.text, byTurn.get(t.id) ?? []) }));
    return { rows: out, unplaced: [...orphans, ...out.flatMap((r) => r.rejected)] };
  }, [turns, highlights]);

  useEffect(() => {
    if (!selectedId || !root.current) return;
    const mark = [...root.current.querySelectorAll<HTMLElement>("mark[data-ids]")].find((m) =>
      m.dataset.ids?.split(" ").includes(selectedId),
    );
    mark?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [selectedId]);

  return (
    <div className="transcript">
      <ol ref={root} className="transcript-turns" aria-label="Transcript">
        {rows.map(({ turn, segments }) => (
          <li key={turn.id} id={`turn-${turn.id}`} className="transcript-turn">
            <p className="transcript-meta">
              <span className="transcript-role">{label(turn)}</span>
              {turn.start_ms != null && <span className="transcript-time"> {formatElapsed(turn.start_ms)}</span>}
            </p>
            <p className="transcript-text">
              {segments.map((s, i) =>
                s.ids.length === 0 ? (
                  <span key={i}>{s.text}</span>
                ) : (
                  <mark
                    key={i}
                    data-ids={s.ids.join(" ")}
                    className={selectedId && s.ids.includes(selectedId) ? "pulse" : undefined}
                  >
                    {s.text}
                  </mark>
                ),
              )}
            </p>
          </li>
        ))}
      </ol>
      {unplaced.length > 0 && (
        <ul className="transcript-unplaced" aria-label="Quotes not highlighted">
          {unplaced.map((h) => (
            <li key={h.id}>{h.quote}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
