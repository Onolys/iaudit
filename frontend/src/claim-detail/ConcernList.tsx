import type { Concern } from "../contract";
import { concernLabel } from "./concernLabels";

interface Props {
  concerns: Concern[];
  /** Evidence ids that can be shown as excerpts. */
  placedIds: Set<string>;
  activeIndex: number | null;
  onToggle: (index: number) => void;
}

export function ConcernList({ concerns, placedIds, activeIndex, onToggle }: Props) {
  if (concerns.length === 0) return null;
  return (
    <section className="cd-concerns" aria-label="Potential concerns">
      <h3>Potential concerns</h3>
      <ul>
        {concerns.map((c, i) => {
          const body = (
            <>
              <strong>{concernLabel(c.type)}</strong>
              <span>{c.explanation}</span>
            </>
          );
          const clickable = c.evidence_ids.some((id) => placedIds.has(id));
          return (
            <li key={i}>
              {clickable ? (
                <button
                  type="button"
                  className="cd-concern"
                  aria-pressed={activeIndex === i}
                  onClick={() => onToggle(i)}
                >
                  {body}
                </button>
              ) : (
                <div className="cd-concern cd-concern-static">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
