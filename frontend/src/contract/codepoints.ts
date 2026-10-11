export function codePointLength(text: string): number {
  return Array.from(text).length;
}

/** End exclusive, in code points. */
export function sliceCodePoints(text: string, start: number, end: number): string {
  return Array.from(text).slice(start, end).join("");
}
