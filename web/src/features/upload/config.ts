/**
 * Language options for the create form (PRD D18, R3). The list is derived from the recorded
 * SP01 gate result (STT check, SP01 R11 (b)), so changing the gate record is the only edit
 * needed when the gate runs.
 */
export type LanguageValue = "auto" | "en-US" | "en-GB";

export interface Language {
  value: LanguageValue;
  label: string;
}

export interface Sp01Gate {
  adr: string;
  status: "pending" | "recorded";
  /** Did diarization work with `auto`? `null` until the gate has run. */
  autoDiarizationOk: boolean | null;
}

/**
 * RECORDED GATE RESULT: docs/decisions/0017-workspace-routes-shared-core.md, "Gate result" is
 * still "Pending" (SP01 T13 needs owner audio), so the PRD default applies. PROVISIONAL.
 * When the gate runs: set `status: "recorded"` and `autoDiarizationOk` from the result.
 */
export const SP01_GATE: Sp01Gate = { adr: "0017", status: "pending", autoDiarizationOk: null };

const ALL: Language[] = [
  { value: "auto", label: "Auto-detect" },
  { value: "en-US", label: "English (US)" },
  { value: "en-GB", label: "English (UK)" },
];

/** `auto` is removed only when the gate shows diarization failed with it. */
export function languagesForGate(gate: Sp01Gate): Language[] {
  return gate.autoDiarizationOk === false ? ALL.filter((l) => l.value !== "auto") : ALL;
}

export const LANGUAGES: Language[] = languagesForGate(SP01_GATE);
export const DEFAULT_LANGUAGE: LanguageValue = LANGUAGES[0]!.value;
