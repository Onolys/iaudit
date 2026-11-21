import type { Diff } from "../../api/report";

export type ChipTone = "agree" | "differs" | "flagged" | "neutral";
export interface Chip {
  text: string;
  tone: ChipTone;
}

const signedText = (n: number) => (n > 0 ? `+${n}` : `${n}`);

/**
 * Scorecard chip for one item (PRD R4). The text says it; the tone only adds colour, so colour is
 * never the only signal. `agree` shows the signed gap (or "Same as you"); `differs`/`flagged` add
 * the status word.
 */
export function diffChip(diff: Diff | undefined): Chip {
  if (!diff) return { text: "–", tone: "neutral" };
  if (diff.status === "not_rated") return { text: "Not rated", tone: "neutral" };
  if (diff.status === "no_onolys_value") return { text: "No Onolys value", tone: "neutral" };
  if (diff.signed === null || diff.signed === undefined) return { text: "–", tone: "neutral" };
  if (diff.signed === 0) return { text: "Same as you", tone: "agree" };
  const base = `Onolys ${signedText(diff.signed)}`;
  if (diff.status === "differs") return { text: `${base} (differs)`, tone: "differs" };
  if (diff.status === "flagged") return { text: `${base} (flagged)`, tone: "flagged" };
  return { text: base, tone: "agree" };
}
