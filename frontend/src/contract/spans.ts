import { codePointLength, sliceCodePoints } from "../utils/codepoints";
import type { AuditRequest, Claim, ClaimCheck, Span } from "./types";

export type SpanSource = "assessment" | "transcript";

export interface Segment {
  index: number;
  from: number;
  to: number;
  length: number;
  text: string;
}

export interface Piece {
  kind: "plain" | "claim";
  from: number;
  to: number;
  text: string;
  claimId?: string;
}

const isNat = (n: number) => Number.isInteger(n) && n >= 0;

/** R3 bounds check. `lengths` = code-point length of each item; claims must stay in one item. */
export function isSpanValid(span: Span, lengths: number[], singleItem: boolean): boolean {
  const { start, end } = span;
  if (![start.index, start.char, end.index, end.char].every(isNat)) return false;
  if (start.index > end.index || end.index >= lengths.length) return false;
  if (singleItem && start.index !== end.index) return false;
  const ordered =
    start.index < end.index || (start.index === end.index && start.char < end.char);
  if (!ordered) return false;
  if (start.char >= lengths[start.index]) return false;
  return end.char <= lengths[end.index];
}

export const itemLengths = (request: AuditRequest, source: SpanSource): number[] =>
  items(request, source).map((i) => codePointLength(i.text));

const items = (request: AuditRequest, source: SpanSource) =>
  source === "assessment" ? request.assessment : request.transcript;

export function walkSpan(request: AuditRequest, span: Span, source: SpanSource): Segment[] {
  const list = items(request, source);
  const lengths = itemLengths(request, source);
  if (!isSpanValid(span, lengths, source === "assessment")) {
    throw new RangeError("span is out of range");
  }
  const { start, end } = span;
  const segments: Segment[] = [];
  for (let index = start.index; index <= end.index; index++) {
    const length = lengths[index];
    const from = index === start.index ? start.char : 0;
    const to = index === end.index ? end.char : length;
    segments.push({ index, from, to, length, text: sliceCodePoints(list[index].text, from, to) });
  }
  return segments;
}

export function segmentSection(
  request: AuditRequest,
  sectionIndex: number,
  checks: Record<string, ClaimCheck>,
  claims: Claim[],
): Piece[] {
  const text = request.assessment[sectionIndex]?.text ?? "";
  const total = codePointLength(text);
  const own = claims
    .filter(
      (c) =>
        c.span.start.index === sectionIndex &&
        checks[c.id]?.claimSpanOk === true,
    )
    .sort((a, b) => a.span.start.char - b.span.start.char);
  const pieces: Piece[] = [];
  const plain = (from: number, to: number) => {
    if (to > from) pieces.push({ kind: "plain", from, to, text: sliceCodePoints(text, from, to) });
  };
  let cursor = 0;
  for (const c of own) {
    const from = c.span.start.char;
    const to = c.span.end.char;
    if (from < cursor) continue; // overlap: stays plain text
    plain(cursor, from);
    pieces.push({ kind: "claim", from, to, text: sliceCodePoints(text, from, to), claimId: c.id });
    cursor = to;
  }
  plain(cursor, total);
  return pieces;
}
