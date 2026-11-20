/**
 * Static MITI 4.2.1 rating-card items (PRD R4, D13): ids match `rating.schema.json` keys
 * (parity-tested in `miti-items.test.ts`); labels and 1-5 anchors are UI copy only.
 */
export interface GlobalItem {
  id: string;
  label: string;
  /** Anchor text for scores 1..5 (index 0 = score 1). */
  anchors: [string, string, string, string, string];
}
export interface CountItem {
  id: string;
  label: string;
}

/** Soft caps: the UI warns past them, the API rejects past them with `rating_invalid`. */
export const LIMITS = { item: 1000, notes: 3000 } as const;

export const GLOBALS: readonly GlobalItem[] = [
  {
    id: "cct",
    label: "Cultivating Change Talk",
    anchors: [
      "Little or no effort to encourage change talk",
      "Some effort, misses most chances",
      "Encourages change talk some of the time",
      "Often encourages change talk",
      "Consistently draws out and strengthens change talk",
    ],
  },
  {
    id: "sst",
    label: "Softening Sustain Talk",
    anchors: [
      "Often prompts or reinforces sustain talk",
      "Sometimes prompts or reinforces it",
      "Neither prompts nor softens it",
      "Often steps around or softens it",
      "Consistently softens sustain talk",
    ],
  },
  {
    id: "partnership",
    label: "Partnership",
    anchors: [
      "Acts as the expert; client is passive",
      "Little collaboration",
      "Some collaboration",
      "Mostly collaborative",
      "Fully collaborative; client's expertise honoured",
    ],
  },
  {
    id: "empathy",
    label: "Empathy",
    anchors: [
      "Little interest in the client's view",
      "Occasional attempts to understand",
      "Moderate effort to understand",
      "Active, solid understanding",
      "Deep, accurate understanding of the client's view",
    ],
  },
];

export const COUNTS: readonly CountItem[] = [
  { id: "gi", label: "Giving Information" },
  { id: "persuade", label: "Persuade" },
  { id: "persuade_permission", label: "Persuade with Permission" },
  { id: "question", label: "Question" },
  { id: "sr", label: "Simple Reflection" },
  { id: "cr", label: "Complex Reflection" },
  { id: "affirm", label: "Affirm" },
  { id: "seek_collab", label: "Seek Collaboration" },
  { id: "emphasize_autonomy", label: "Emphasize Autonomy" },
  { id: "confront", label: "Confront" },
];
