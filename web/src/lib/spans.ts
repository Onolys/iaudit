/**
 * Highlight segmenter (idea copied from `frontend/src/contract/spans.ts`, PRD D2). Spans are
 * code-point offsets into one turn's text. Overlapping spans are split so each segment lists every
 * covering id. A span that is invalid or whose quote differs from the slice is rejected (drift
 * between report and transcript): the text stays unhighlighted and the caller shows the quote.
 */
import { buildIndexMap } from "./codepoints";

export interface SpanInput {
  id: string;
  start: number;
  end: number;
  quote: string;
}

export interface Segment {
  text: string;
  ids: string[];
}

export interface SegmentResult {
  segments: Segment[];
  rejected: SpanInput[];
}

const isNat = (n: number) => Number.isInteger(n) && n >= 0;

export function buildSegments(text: string, spans: SpanInput[]): SegmentResult {
  const map = buildIndexMap(text);
  const total = map.length - 1;
  const rejected: SpanInput[] = [];
  const valid: SpanInput[] = [];
  for (const s of spans) {
    const ok = isNat(s.start) && isNat(s.end) && s.start < s.end && s.end <= total;
    if (ok && text.slice(map[s.start], map[s.end]) === s.quote) valid.push(s);
    else rejected.push(s);
  }
  if (rejected.length && import.meta.env.DEV) {
    console.warn("transcript: span does not match turn text", rejected.map((r) => r.id));
  }
  const cuts = new Set<number>([0, total]);
  for (const s of valid) {
    cuts.add(s.start);
    cuts.add(s.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const segments: Segment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const from = points[i];
    const to = points[i + 1];
    const ids = valid.filter((s) => s.start <= from && s.end >= to).map((s) => s.id);
    segments.push({ text: text.slice(map[from], map[to]), ids });
  }
  if (segments.length === 0) segments.push({ text, ids: [] });
  return { segments, rejected };
}
