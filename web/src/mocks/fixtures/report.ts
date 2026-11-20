/**
 * Typed report fixtures (SP03 R7 shape). Offsets are computed from the
 * transcript so quote slices are exact in code points.
 */
import type { Explanation, Line, Report } from "../../api/report";
import { edgeTranscript, sampleTranscript, type Turn } from "./transcripts";

/** [turn id, substring of that turn's text] per quote key. */
type Picks = Record<"cct1" | "cct2" | "sust" | "sr" | "cr" | "q" | "aff" | "aut", [string, string]>;

const STANDARD_PICKS: Picks = {
  cct1: ["t2", "I'd like to start walking more"],
  cct2: ["t6", "a short walk around the block would feel good"],
  sust: ["t4", "it gets dark early and I'm usually exhausted"],
  sr: ["t3", "You'd like to walk more in the evenings."],
  cr: ["t5", "part of you still wants to get out there"],
  q: ["t7", "What would make three evenings feel doable?"],
  aff: ["t9", "That's a thoughtful plan"],
  aut: ["t9", "it's yours to adjust"],
};

const EDGE_PICKS: Picks = {
  cct1: ["t2", "I'd like to start walking more"],
  cct2: ["t6", "would feel good"],
  sust: ["t4", "and I'm usually exhausted"],
  sr: ["t3", "in the evenings."],
  cr: ["t5", "and part of you still wants to get out there"],
  q: ["t7", "feel doable?"],
  aff: ["t9", "and it's yours to adjust"],
  aut: ["t9", "it's yours to adjust"],
};

/** Code-point offsets of `sub` inside `text` (JS strings are UTF-16). */
function cpRange(text: string, sub: string): { start: number; end: number } {
  const i = text.indexOf(sub);
  if (i < 0) throw new Error(`fixture quote not found: ${sub}`);
  const start = Array.from(text.slice(0, i)).length;
  return { start, end: start + Array.from(sub).length };
}

function lineFor(turns: Turn[], [turnId, sub]: [string, string]): Line {
  const turn = turns.find((t) => t.id === turnId);
  if (!turn) throw new Error(`fixture turn not found: ${turnId}`);
  return { turn_id: turnId, ...cpRange(turn.text, sub), quote: sub };
}

const ITEMS: { id: string; kind: "global" | "count"; label: string }[] = [
  { id: "cct", kind: "global", label: "Cultivating Change Talk" },
  { id: "sst", kind: "global", label: "Softening Sustain Talk" },
  { id: "partnership", kind: "global", label: "Partnership" },
  { id: "empathy", kind: "global", label: "Empathy" },
  { id: "gi", kind: "count", label: "Giving Information" },
  { id: "persuade", kind: "count", label: "Persuade" },
  { id: "persuade_permission", kind: "count", label: "Persuade with Permission" },
  { id: "question", kind: "count", label: "Question" },
  { id: "sr", kind: "count", label: "Simple Reflection" },
  { id: "cr", kind: "count", label: "Complex Reflection" },
  { id: "affirm", kind: "count", label: "Affirm" },
  { id: "seek_collab", kind: "count", label: "Seek Collaboration" },
  { id: "emphasize_autonomy", kind: "count", label: "Emphasize Autonomy" },
  { id: "confront", kind: "count", label: "Confront" },
];

// [item id]: [clinician value, onolys value, status]
const GLOBAL_VALUES: Record<string, [number, number, "agree" | "differs"]> = {
  cct: [4, 2, "differs"],
  sst: [3, 3, "agree"],
  partnership: [4, 4, "agree"],
  empathy: [3, 4, "agree"],
};
const COUNT_VALUES: Record<string, [number, number, "agree" | "differs" | "flagged"]> = {
  gi: [2, 2, "agree"],
  persuade: [0, 0, "agree"],
  persuade_permission: [0, 0, "agree"],
  question: [4, 4, "agree"],
  sr: [3, 1, "differs"],
  cr: [1, 3, "flagged"],
  affirm: [1, 1, "agree"],
  seek_collab: [0, 0, "agree"],
  emphasize_autonomy: [1, 1, "agree"],
  confront: [0, 0, "agree"],
};

const NO_EXPLANATION: Explanation = {
  headline: "",
  body: [],
  onolys_lines: [],
  clinician_support_lines: [],
};

function diffOf(c: number, o: number, status: "agree" | "differs" | "flagged") {
  const signed = o - c;
  return {
    signed,
    abs: Math.abs(signed),
    direction: signed === 0 ? "same" : signed > 0 ? "onolys_higher" : "onolys_lower",
    status,
    within_one: Math.abs(signed) <= 1,
  };
}

function stats(v: number) {
  return { mean: v, min: v, max: v, values: [v] };
}

function build(turns: Turn[], picks: Picks): Report {
  const L = Object.fromEntries(
    Object.entries(picks).map(([k, p]) => [k, lineFor(turns, p)]),
  ) as Record<keyof Picks, Line>;

  const instancesByCode: Record<string, Line[]> = {
    sr: [L.sr],
    cr: [L.cr],
    question: [L.q],
    affirm: [L.aff],
    emphasize_autonomy: [L.aut],
  };

  const scorecard: Report["scorecard"] = ITEMS.map((it) => {
    const [c, o, status] = it.kind === "global" ? GLOBAL_VALUES[it.id] : COUNT_VALUES[it.id];
    return {
      item_id: it.id,
      kind: it.kind,
      label: it.label,
      clinician: { value: c },
      onolys: { value: o, ...stats(o) },
      diff: diffOf(c, o, status),
    };
  });

  const globals: Report["globals"] = ITEMS.filter((i) => i.kind === "global").map((it) => {
    const [c, o, status] = GLOBAL_VALUES[it.id];
    const differs = status === "differs";
    return {
      item_id: it.id,
      onolys: {
        score: o,
        source: "model",
        reason: differs
          ? "Onolys reads the change talk here as present but mostly early-stage."
          : "Onolys reads this as in line with the self-rating.",
        evidence: it.id === "cct" ? [L.cct1, L.cct2] : [],
      },
      clinician: { value: c, reason: differs ? "Several clear statements about walking more." : undefined },
      diff: diffOf(c, o, status),
      explanation: differs
        ? {
            headline: "Onolys disagrees on Cultivating Change Talk, here's why",
            body: [
              "Onolys reads the client's statements as a wish rather than a firm commitment.",
              "Your rating counted the plan for three evenings a week as strong change talk.",
            ],
            onolys_lines: [L.cct1],
            clinician_support_lines: [L.cct2],
          }
        : NO_EXPLANATION,
    };
  });

  const behaviours: Report["behaviours"] = ITEMS.filter((i) => i.kind === "count").map((it) => {
    const [c, o, status] = COUNT_VALUES[it.id];
    const instances = (instancesByCode[it.id] ?? []).map((l, i) => ({
      id: `${it.id}-${i + 1}`,
      ...l,
      rationale: `Onolys counted this as ${it.label.toLowerCase()}.`,
    }));
    return {
      item_id: it.id,
      clinician_count: c,
      onolys_count: stats(o),
      instances,
      instances_total: it.id === "cr" ? 3 : instances.length,
      diff: diffOf(c, o, status),
      explanation:
        status === "flagged"
          ? {
              headline: "Onolys counted more complex reflections than you did",
              body: ["Some reflections add meaning beyond what the client said."],
              onolys_lines: [L.cr],
              clinician_support_lines: [],
            }
          : NO_EXPLANATION,
    };
  });

  return {
    schema_version: "0.0.1",
    created_at: "2026-11-20T09:30:00.000Z",
    header: {
      change_goal: "Walk more in the evenings",
      protocol: { id: "miti", version: "4.2.1", pack_hash: "sample0000", label: "MITI 4.2.1" },
      language: "en-US",
      coded_span: null,
      subject_speaker: "spk_0",
      n_runs: 1,
      models: { paudit: "mock-model-a", eaudit: "mock-model-b", tips: "mock-model-a" },
      stt: {
        provider: "mock",
        model: "mock-stt",
        location: "local",
        language_requested: "auto",
        language_detected: "en-US",
        adapter_version: "0.0.0",
      },
      preset: "default",
      code_version: "mock",
      params: {},
      has_clinician_rating: true,
      rating_coverage: { rated: 14, total: 14 },
    },
    layout: [
      { section: "scorecard", title: "Scorecard" },
      { section: "disagreements", title: "Where Onolys disagrees" },
      { section: "globals", title: "Global scores" },
      { section: "behaviours", title: "Behaviour counts" },
      { section: "summaries", title: "Summary measures" },
      { section: "reasons_audit", title: "Your reasons, checked" },
      { section: "tips", title: "Tips" },
      { section: "method", title: "About this report" },
    ],
    scorecard,
    globals,
    behaviours,
    summaries: [
      {
        id: "pct_cr",
        label: "Complex reflections / all reflections",
        clinician: { value: 0.25, label: "25%" },
        onolys: { value: 0.75, label: "75%" },
        reference: { fair: 0.4, good: 0.5 },
        note: "Reference levels, not pass marks.",
      },
      {
        id: "r_to_q",
        label: "Reflections per question",
        clinician: { value: 1, label: "1.0" },
        onolys: { value: 1, label: "1.0" },
        reference: { fair: 1, good: 2 },
        note: "Reference levels, not pass marks.",
      },
    ],
    reasons_audit: {
      status: "ran",
      items: [
        {
          item_id: "cct",
          reason: "Several clear statements about walking more.",
          claims: [
            {
              span: "Several clear statements about walking more.",
              verdict: "partially_supported",
              explanation: "Two statements support this; one is a wish rather than a plan.",
              concerns: [],
              evidence: [
                { role: "supporting", ...L.cct1 },
                { role: "qualifying", ...L.sust },
              ],
            },
          ],
        },
        {
          item_id: "notes",
          reason: "The client was tired but engaged.",
          claims: [
            {
              span: "The client was tired but engaged.",
              verdict: "supported",
              explanation: "The client names tiredness and still proposes a plan.",
              concerns: [],
              evidence: [{ role: "supporting", ...L.sust }],
            },
          ],
        },
      ],
    },
    tips: [
      {
        rank: 1,
        item_id: "cr",
        observation: "A reflection could add the client's reason for change.",
        quote: { turn_id: L.sr.turn_id, start: L.sr.start, end: L.sr.end, text: L.sr.quote },
        alternative: "You might add what walking would give them.",
        why_it_matters: "Reflections that add meaning invite more change talk.",
      },
      {
        rank: 2,
        item_id: "question",
        observation: "An open question gave the client room to plan.",
        quote: { turn_id: L.q.turn_id, start: L.q.start, end: L.q.end, text: L.q.quote },
        alternative: "A follow-up could ask what would help most.",
        why_it_matters: "Planning in the client's words builds commitment.",
      },
      {
        rank: 3,
        item_id: "emphasize_autonomy",
        observation: "Naming the client's choice supported their plan.",
        quote: { turn_id: L.aut.turn_id, start: L.aut.start, end: L.aut.end, text: L.aut.quote },
        alternative: "You could pair it with a reflection of their plan.",
        why_it_matters: "Autonomy support keeps the client in charge.",
      },
    ],
    method: {
      statement:
        "Onolys is an AI reading of this session against MITI 4.2.1. It is not official MITI coding.",
      limits: ["Based on a transcript only", "Tone and timing are not scored"],
      not_official_miti_coding: true,
      citation: "Moyers et al., MITI 4.2.1 coding manual",
    },
    aggregates: {
      globals_compared: 4,
      avg_abs_global_difference: 0.75,
      within_one_share: 0.75,
      counts_flagged: 1,
    },
    warnings: [],
    run_info: { evaluation: {}, paudit: {}, eaudit: {} },
  };
}

function noRating(base: Report): Report {
  const r = structuredClone(base);
  const notRated = { signed: null, abs: null, direction: null, status: "not_rated" as const };
  r.header.has_clinician_rating = false;
  r.header.rating_coverage = { rated: 0, total: 14 };
  for (const s of r.scorecard) {
    s.clinician = { value: null };
    s.diff = { ...notRated };
  }
  for (const g of r.globals) {
    g.clinician = { value: null };
    g.diff = { ...notRated };
    g.explanation = { ...NO_EXPLANATION };
  }
  for (const b of r.behaviours) {
    b.clinician_count = null;
    b.diff = { ...notRated };
    b.explanation = { ...NO_EXPLANATION };
  }
  for (const s of r.summaries) s.clinician = null;
  r.reasons_audit = { status: "skipped", items: [] };
  r.aggregates = {
    globals_compared: 0,
    avg_abs_global_difference: null,
    within_one_share: null,
    counts_flagged: null,
  };
  return r;
}

/** The committed N=1 report that `/sample-report` also renders. */
export const sampleReport: Report = build(sampleTranscript, STANDARD_PICKS);
export const noRatingReport: Report = noRating(sampleReport);
export const reasonsFailedReport: Report = {
  ...structuredClone(sampleReport),
  reasons_audit: { status: "failed", items: [] },
  warnings: [{ code: "reasons_audit_failed" }],
};
export const noTipsReport: Report = {
  ...structuredClone(sampleReport),
  tips: [],
  warnings: [{ code: "tips_failed" }],
};
/** Report over `edgeTranscript`: quotes sit after astral emoji / ZWJ / combining marks. */
export const edgeReport: Report = build(edgeTranscript, EDGE_PICKS);

export interface ReportOptions {
  edge?: boolean;
  hasRating: boolean;
  reasonsFailed?: boolean;
  tipsFailed?: boolean;
  createdAt?: string;
}

/** Pick/derive the fixture report for a mock run. */
export function reportFor(o: ReportOptions): Report {
  let r = structuredClone(o.edge ? edgeReport : sampleReport);
  if (!o.hasRating) r = noRating(r);
  if (o.reasonsFailed && o.hasRating) {
    r.reasons_audit = { status: "failed", items: [] };
    r.warnings.push({ code: "reasons_audit_failed" });
  }
  if (o.tipsFailed) {
    r.tips = [];
    r.warnings.push({ code: "tips_failed" });
  }
  if (o.createdAt) r.created_at = o.createdAt;
  return r;
}
