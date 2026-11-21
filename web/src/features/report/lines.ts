import type { Line, Report } from "../../api/report";
import type { Highlight } from "../transcript/Transcript";

/**
 * Every evidence line in a report gets a stable id so a button can select it (`#i=<id>`) and the
 * transcript can highlight it. Instances keep the report's own `instances[].id`.
 */
export const lineId = {
  explain: (item: string, side: "o" | "c", i: number) => `ln.x.${item}.${side}.${i}`,
  evidence: (item: string, i: number) => `ln.g.${item}.${i}`,
  claim: (item: string, claim: number, i: number) => `ln.a.${item}.${claim}.${i}`,
  tip: (rank: number) => `ln.t.${rank}`,
};

const hl = (id: string, l: { turn_id: string; start: number; end: number; quote: string }): Highlight => ({
  id,
  turn_id: l.turn_id,
  start: l.start,
  end: l.end,
  quote: l.quote,
});

/** All lines of a report as transcript highlights. Tips map `quote.text` to the segmenter's `quote`. */
export function reportHighlights(r: Report): Highlight[] {
  const out: Highlight[] = [];
  const lines = (ls: Line[] | undefined, id: (i: number) => string) =>
    (ls ?? []).forEach((l, i) => out.push(hl(id(i), l)));
  for (const g of r.globals ?? []) {
    lines(g.onolys?.evidence, (i) => lineId.evidence(g.item_id, i));
    lines(g.explanation?.onolys_lines, (i) => lineId.explain(g.item_id, "o", i));
    lines(g.explanation?.clinician_support_lines, (i) => lineId.explain(g.item_id, "c", i));
  }
  for (const b of r.behaviours ?? []) {
    for (const inst of b.instances ?? []) out.push(hl(inst.id, inst));
    lines(b.explanation?.onolys_lines, (i) => lineId.explain(b.item_id, "o", i));
    lines(b.explanation?.clinician_support_lines, (i) => lineId.explain(b.item_id, "c", i));
  }
  for (const item of r.reasons_audit?.items ?? [])
    (item.claims ?? []).forEach((c, ci) => lines(c.evidence, (i) => lineId.claim(item.item_id, ci, i)));
  for (const t of r.tips ?? [])
    out.push(hl(lineId.tip(t.rank), { turn_id: t.quote.turn_id, start: t.quote.start, end: t.quote.end, quote: t.quote.text }));
  return out;
}
