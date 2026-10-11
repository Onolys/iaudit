import { Fragment, useMemo, useState } from "react";
import type { AuditRequest, Evidence, Expansion, Verdict } from "../contract";
import { buildChunks } from "../contract";
import { ROLE_STYLE } from "../tokens";
import { ExpandControl } from "./ExpandControl";
import { ChunkView } from "./ChunkView";
import { toExcerptViews } from "./excerptModel";

interface Props {
  request: AuditRequest;
  placed: Evidence[];
  unplaceable: Evidence[];
  verdict: Verdict;
  /** Number of evidence entries on the claim, shown or not. */
  evidenceCount: number;
  activeIds: Set<string> | null;
}

export function ExcerptList({ request, placed, unplaceable, verdict, evidenceCount, activeIds }: Props) {
  const [expansion, setExpansion] = useState<Record<string, Expansion>>({});
  const grow = (id: string, dir: keyof Expansion) =>
    setExpansion((cur) => {
      const { up = 0, down = 0 } = cur[id] ?? {};
      return { ...cur, [id]: { up, down, [dir]: (dir === "up" ? up : down) + 1 } };
    });
  const views = useMemo(() => toExcerptViews(request, placed), [request, placed]);
  const byId = useMemo(() => new Map(views.map((v) => [v.ev.id, v])), [views]);
  const chunks = useMemo(
    () =>
      buildChunks({
        transcriptLength: request.transcript.length,
        excerpts: views.map((v) => ({ id: v.ev.id, firstTurn: v.firstTurn, lastTurn: v.lastTurn })),
        expansion,
      }),
    [request, views, expansion],
  );
  return (
    <section className="cd-excerpts" aria-label="Excerpts">
      <h3>Excerpts</h3>
      {chunks.length === 0 && (
        <p className="cd-empty">
          {verdict === "insufficient_evidence" && evidenceCount === 0
            ? "No excerpt in the supplied interview."
            : "No excerpts to show."}
        </p>
      )}
      {chunks.map((chunk, i) => {
        const next = chunks[i + 1];
        return (
          <Fragment key={chunk.startTurn}>
            {i === 0 && (
              <ExpandControl up={{ hidden: chunk.hiddenAbove, onClick: () => grow(chunk.topExcerptId, "up") }} />
            )}
            <ChunkView chunk={chunk} request={request} views={byId} activeIds={activeIds} />
            {next ? (
              <ExpandControl
                down={{ hidden: chunk.hiddenBelow, onClick: () => grow(chunk.bottomExcerptId, "down") }}
                up={{ hidden: next.hiddenAbove, onClick: () => grow(next.topExcerptId, "up") }}
              />
            ) : (
              <ExpandControl down={{ hidden: chunk.hiddenBelow, onClick: () => grow(chunk.bottomExcerptId, "down") }} />
            )}
          </Fragment>
        );
      })}
      {unplaceable.map((ev) => (
        <p key={ev.id} className="cd-oor">
          Excerpt position out of range — {ROLE_STYLE[ev.role].label}
          {ev.note ? ` — ${ev.note}` : ""}
        </p>
      ))}
    </section>
  );
}
