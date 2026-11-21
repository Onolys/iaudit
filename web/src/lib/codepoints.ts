/** Offsets from paudit/eaudit are Unicode code points; JS strings index UTF-16 units (PRD D11). */

export function codePointLength(text: string): number {
  let n = 0;
  for (const _ of text) n++; // eslint-disable-line @typescript-eslint/no-unused-vars
  return n;
}

/** `map[cp]` = UTF-16 index of code point `cp`; length is codePointLength + 1 (last entry = text.length). */
export function buildIndexMap(text: string): number[] {
  const map: number[] = [];
  let unit = 0;
  for (const ch of text) {
    map.push(unit);
    unit += ch.length;
  }
  map.push(unit);
  return map;
}

/** Slice by code point, end exclusive. */
export function sliceCodePoints(text: string, start: number, end: number): string {
  const map = buildIndexMap(text);
  return text.slice(map[start], map[end]);
}
// preview cleanup re-proof (scratch, do not merge)
