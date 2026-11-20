import { describe, expect, it } from "vitest";
import type { Line, Report } from "../../api/report";
import type { components } from "../../api/schema";
import {
  edgeReport,
  edgeTranscript,
  noRatingReport,
  noTipsReport,
  reasonsFailedReport,
  sampleReport,
  sampleTranscript,
  threeSpeakerTranscript,
} from ".";

type Turn = components["schemas"]["TranscriptTurn"];

const cpSlice = (text: string, start: number, end: number) =>
  Array.from(text).slice(start, end).join("");

const DIFF_STATUS = ["agree", "differs", "flagged", "not_rated", "no_onolys_value"];
const VERDICTS = ["supported", "partially_supported", "contradicted", "insufficient_evidence", "out_of_scope"];
const ROLES = ["supporting", "contradicting", "qualifying"];
const SECTIONS = ["scorecard", "disagreements", "globals", "behaviours", "summaries", "reasons_audit", "tips", "method"];

/**
 * Typed shape check standing in for validation against
 * `engines/evaluation/schemas/report.schema.json` (not in the repo yet).
 * Swap for an Ajv validation once the schema exists (SP05 T13).
 */
function checkReportShape(r: Report): string[] {
  const errs: string[] = [];
  const need = (ok: boolean, msg: string) => ok || errs.push(msg);
  need(r.schema_version === "0.0.1", "schema_version");
  need(typeof r.created_at === "string", "created_at");
  for (const k of ["change_goal", "language", "subject_speaker", "preset", "code_version"] as const)
    need(typeof r.header[k] === "string", `header.${k}`);
  need(r.header.protocol.label.length > 0, "header.protocol.label");
  need(typeof r.header.stt.provider === "string", "header.stt");
  need(r.header.n_runs >= 1, "header.n_runs");
  need(r.layout.length > 0 && r.layout.every((l) => l.section && l.title), "layout");
  for (const s of r.scorecard) {
    need(["global", "count"].includes(s.kind), `scorecard.${s.item_id}.kind`);
    need(DIFF_STATUS.includes(s.diff.status), `scorecard.${s.item_id}.diff.status`);
    need(Array.isArray(s.onolys.values), `scorecard.${s.item_id}.onolys.values`);
  }
  for (const g of r.globals) need(DIFF_STATUS.includes(g.diff.status), `globals.${g.item_id}`);
  for (const b of r.behaviours) {
    need(b.instances_total >= b.instances.length, `behaviours.${b.item_id}.instances_total`);
    need(DIFF_STATUS.includes(b.diff.status), `behaviours.${b.item_id}`);
  }
  need(["ran", "partial", "skipped", "failed"].includes(r.reasons_audit.status), "reasons_audit.status");
  for (const it of r.reasons_audit.items)
    for (const c of it.claims) {
      need(VERDICTS.includes(c.verdict), "claim.verdict");
      for (const e of c.evidence) need(ROLES.includes(e.role), "evidence.role");
    }
  r.tips.forEach((t, i) => need(t.rank === i + 1, "tips.rank"));
  need(r.method.not_official_miti_coding === true, "method.not_official_miti_coding");
  need(r.method.limits.length > 0, "method.limits");
  need(Array.isArray(r.warnings), "warnings");
  return errs;
}

function allLines(r: Report): Line[] {
  const lines: Line[] = [];
  for (const g of r.globals) {
    lines.push(...g.onolys.evidence, ...g.explanation.onolys_lines, ...g.explanation.clinician_support_lines);
  }
  for (const b of r.behaviours) {
    lines.push(...b.instances, ...b.explanation.onolys_lines, ...b.explanation.clinician_support_lines);
  }
  for (const it of r.reasons_audit.items) for (const c of it.claims) lines.push(...c.evidence);
  for (const t of r.tips) lines.push({ ...t.quote, quote: t.quote.text });
  return lines;
}

const variants: [string, Report, Turn[]][] = [
  ["sample (N=1, rated)", sampleReport, sampleTranscript],
  ["no-rating", noRatingReport, sampleTranscript],
  ["reasons_audit failed", reasonsFailedReport, sampleTranscript],
  ["no tips", noTipsReport, sampleTranscript],
  ["utf-8 edge", edgeReport, edgeTranscript],
];

describe.each(variants)("report fixture: %s", (_name, report, turns) => {
  it("has the documented report shape", () => {
    expect(checkReportShape(report)).toEqual([]);
  });

  it("every quote equals the transcript slice at its code-point offsets", () => {
    const lines = allLines(report);
    expect(lines.length).toBeGreaterThan(0);
    for (const l of lines) {
      const turn = turns.find((t) => t.id === l.turn_id);
      expect(turn, `turn ${l.turn_id}`).toBeDefined();
      expect(cpSlice(turn!.text, l.start, l.end)).toBe(l.quote);
    }
  });
});

describe("sample report content", () => {
  it("is N=1 and covers the 14 MITI items from the layout order", () => {
    expect(sampleReport.header.n_runs).toBe(1);
    expect(sampleReport.scorecard.map((s) => s.item_id)).toEqual([
      "cct", "sst", "partnership", "empathy",
      "gi", "persuade", "persuade_permission", "question", "sr", "cr", "affirm", "seek_collab", "emphasize_autonomy", "confront",
    ]);
    expect(sampleReport.layout.map((l) => l.section)).toEqual(SECTIONS);
    expect(sampleReport.header.stt.provider).toBeTruthy();
    expect(sampleReport.header.preset).toBeTruthy();
    expect(sampleReport.header.code_version).toBeTruthy();
  });

  it("has a global that differs, a count that is flagged, and a count that only differs", () => {
    const g = sampleReport.globals.filter((x) => x.diff.status === "differs");
    expect(g.length).toBeGreaterThan(0);
    expect(g[0].explanation.headline).toBeTruthy();
    expect(g[0].explanation.onolys_lines.length).toBeGreaterThan(0);
    expect(g[0].explanation.clinician_support_lines.length).toBeGreaterThan(0);
    const flagged = sampleReport.behaviours.filter((x) => x.diff.status === "flagged");
    const differs = sampleReport.behaviours.filter((x) => x.diff.status === "differs");
    expect(flagged.length).toBeGreaterThan(0);
    expect(differs.length).toBeGreaterThan(0);
    expect(flagged[0].explanation.headline).toBeTruthy();
    expect(differs[0].explanation.headline).toBe("");
    expect(flagged.some((b) => b.instances_total > b.instances.length)).toBe(true);
  });

  it("includes reasons audit (ran), 3 tips, and reference levels", () => {
    expect(sampleReport.reasons_audit.status).toBe("ran");
    expect(sampleReport.tips).toHaveLength(3);
    expect(sampleReport.summaries.every((s) => s.reference.good > s.reference.fair)).toBe(true);
  });

  it("is synthetic: no PHI-like content", () => {
    const text = JSON.stringify(sampleReport) + JSON.stringify(sampleTranscript);
    expect(text).not.toMatch(/@|\b\d{3}[- ]\d{3,4}[- ]\d{4}\b/);
  });
});

describe("no-rating report", () => {
  it("has Onolys values only", () => {
    expect(noRatingReport.header.has_clinician_rating).toBe(false);
    expect(noRatingReport.scorecard.every((s) => s.clinician.value === null)).toBe(true);
    expect(noRatingReport.scorecard.every((s) => s.diff.status === "not_rated")).toBe(true);
    expect(noRatingReport.scorecard.every((s) => s.onolys.value !== null)).toBe(true);
    expect(noRatingReport.reasons_audit.status).toBe("skipped");
    expect(noRatingReport.aggregates.avg_abs_global_difference).toBeNull();
    expect(noRatingReport.summaries.every((s) => s.clinician === null)).toBe(true);
    expect(noRatingReport.tips.length).toBeGreaterThan(0);
  });
});

describe("failure-variant reports", () => {
  it("reasons_audit failed keeps the rest of the report", () => {
    expect(reasonsFailedReport.reasons_audit).toEqual({ status: "failed", items: [] });
    expect(reasonsFailedReport.warnings.map((w) => w.code)).toContain("reasons_audit_failed");
    expect(reasonsFailedReport.scorecard).toEqual(sampleReport.scorecard);
    expect(reasonsFailedReport.tips).toEqual(sampleReport.tips);
  });

  it("no-tips report has an empty tips list and a warning", () => {
    expect(noTipsReport.tips).toEqual([]);
    expect(noTipsReport.warnings.map((w) => w.code)).toContain("tips_failed");
  });
});

describe("transcripts", () => {
  it("UTF-8 edge transcript has astral emoji, ZWJ sequences and combining marks", () => {
    const text = edgeTranscript.map((t) => t.text).join("\n");
    expect(text).toMatch(/[\u{1F300}-\u{1FAFF}]/u);
    expect(text).toContain("‍"); // ZWJ
    expect(text).toMatch(/\p{M}/u); // combining mark
    // UTF-16 length differs from code-point count => offsets must be code points
    expect(text.length).toBeGreaterThan(Array.from(text).length);
  });

  it("edge report instances sit after astral characters (offsets differ between UTF-16 and code points)", () => {
    const shifted = allLines(edgeReport).filter((l) => {
      const t = edgeTranscript.find((x) => x.id === l.turn_id)!;
      return t.text.slice(l.start, l.end) !== l.quote;
    });
    expect(shifted.length).toBeGreaterThan(0);
  });

  it("three-speaker transcript has exactly three speakers, each with at least 3 turns", () => {
    const counts = new Map<string, number>();
    for (const t of threeSpeakerTranscript) counts.set(t.speaker, (counts.get(t.speaker) ?? 0) + 1);
    expect([...counts.keys()].sort()).toEqual(["spk_0", "spk_1", "spk_2"]);
    for (const n of counts.values()) expect(n).toBeGreaterThanOrEqual(3);
  });

  it("turn ids are unique and sequential", () => {
    for (const ts of [sampleTranscript, edgeTranscript, threeSpeakerTranscript])
      expect(new Set(ts.map((t) => t.id)).size).toBe(ts.length);
  });
});
