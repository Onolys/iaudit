import { useMemo } from "react";
import type { AuditRequest, Evidence } from "../contract";
import { buildChunks } from "../contract";
import { ROLE_STYLE } from "../tokens";
import { ChunkView } from "./ChunkView";
import { toExcerptViews } from "./excerptModel";

interface Props {
  request: AuditRequest;
  placed: Evidence[];
  unplaceable: Evidence[];
  activeIds: Set<string> | null;
}

export function ExcerptList({ request, placed, unplaceable, activeIds }: Props) {
  const views = useMemo(() => toExcerptViews(request, placed), [request, placed]);
  const byId = useMemo(() => new Map(views.map((v) => [v.ev.id, v])), [views]);
  const chunks = useMemo(
    () =>
      buildChunks({
        transcriptLength: request.transcript.length,
        excerpts: views.map((v) => ({ id: v.ev.id, firstTurn: v.firstTurn, lastTurn: v.lastTurn })),
        expansion: {},
      }),
    [request, views],
  );
  if (views.length === 0 && unplaceable.length === 0) return null;
  return (
    <section className="cd-excerpts" aria-label="Excerpts">
      <h3>Excerpts</h3>
      {chunks.map((chunk) => (
        <ChunkView key={chunk.startTurn} chunk={chunk} request={request} views={byId} activeIds={activeIds} />
      ))}
      {unplaceable.map((ev) => (
        <p key={ev.id} className="cd-oor">
          Excerpt position out of range — {ROLE_STYLE[ev.role].label}
          {ev.note ? ` — ${ev.note}` : ""}
        </p>
      ))}
    </section>
  );
}
