import type { AuditRequest, Evidence } from "../contract";
import { walkSpan } from "../contract";

/** A placed piece of evidence with the exact per-turn character ranges it covers. */
export interface ExcerptView {
  ev: Evidence;
  /** Position among placed evidence (transcript order); lower = listed first. */
  order: number;
  firstTurn: number;
  lastTurn: number;
  ranges: Map<number, { from: number; to: number }>;
}

export function toExcerptViews(request: AuditRequest, placed: Evidence[]): ExcerptView[] {
  return placed.map((ev, order) => {
    const segments = walkSpan(request, ev.span, "transcript");
    return {
      ev,
      order,
      firstTurn: segments[0].index,
      lastTurn: segments[segments.length - 1].index,
      ranges: new Map(segments.map((s) => [s.index, { from: s.from, to: s.to }])),
    };
  });
}

export interface TextPart {
  from: number;
  to: number;
  kind: "plain" | "highlight" | "overlap" | "dim";
}

/**
 * Split one turn at every highlight boundary. Covered by one excerpt = highlight,
 * by two or more = overlap, uncovered text inside an excerpt row = dim.
 * A row with no excerpt (context only) is a single plain part.
 */
export function partsForTurn(length: number, covering: { from: number; to: number }[]): TextPart[] {
  if (covering.length === 0) return [{ from: 0, to: length, kind: "plain" }];
  const cuts = [...new Set([0, length, ...covering.flatMap((r) => [r.from, r.to])])].sort((a, b) => a - b);
  const parts: TextPart[] = [];
  for (let i = 0; i < cuts.length - 1; i++) {
    const [from, to] = [cuts[i], cuts[i + 1]];
    const n = covering.filter((r) => r.from <= from && r.to >= to).length;
    parts.push({ from, to, kind: n === 0 ? "dim" : n === 1 ? "highlight" : "overlap" });
  }
  return parts;
}
