import { CONCERN_GROUP_LABELS } from "../contract";
import type { Concern, ConcernGroup } from "../contract";
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
      {(Object.keys(CONCERN_GROUP_LABELS) as ConcernGroup[]).map((group) => {
        const members = concerns.map((concern, index) => ({ concern, index }))
          .filter(({ concern }) => concern.group === group);
        if (members.length === 0) return null;
        return (
          <div key={group}>
            <h4>{CONCERN_GROUP_LABELS[group]}</h4>
            <ul>
              {members.map(({ concern: c, index: i }) => {
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
          </div>
        );
      })}
    </section>
  );
}
