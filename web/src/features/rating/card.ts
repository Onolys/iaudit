/** Rating form state <-> API card (`rating.schema.json`), local checks and 422 mapping (PRD R4). */
import type { ApiError } from "../../api/errors";
import type { components } from "../../api/schema";
import { COUNTS, GLOBALS, LIMITS } from "../../protocol/miti-items";

export type Card = components["schemas"]["RatingCard"];

export interface GlobalForm { score: string; reason: string; exTime: string; exText: string }
export interface CountForm { count: string; note: string }
export interface RatingForm {
  changeGoal: string;
  spanFrom: string;
  spanTo: string;
  globals: Record<string, GlobalForm>;
  counts: Record<string, CountForm>;
  notes: string;
}

export const emptyForm = (): RatingForm => ({
  changeGoal: "",
  spanFrom: "",
  spanTo: "",
  globals: Object.fromEntries(GLOBALS.map((g) => [g.id, { score: "", reason: "", exTime: "", exText: "" }])),
  counts: Object.fromEntries(COUNTS.map((c) => [c.id, { count: "", note: "" }])),
  notes: "",
});

const CLOCK = /^(\d+):([0-5]\d)$/;
/** `mm:ss` (minutes may exceed 59) to seconds; undefined when blank or malformed. */
export function parseClock(s: string): number | undefined {
  const m = CLOCK.exec(s.trim());
  return m ? Number(m[1]) * 60 + Number(m[2]) : undefined;
}
export function formatClock(sec: number): string {
  const t = Math.max(0, Math.floor(sec));
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
}

export function softCount(value: string, limit: number) {
  const length = [...value].length; // code points, like the API's length check
  return { length, limit, over: length > limit };
}

const blank = (s: string) => s.trim() === "";
const parseCount = (s: string): number | undefined => (/^\d+$/.test(s.trim()) ? Number(s.trim()) : undefined);

/** Build the card sent to the API. Empty parts are omitted; unparseable times/counts are dropped. */
export function buildCard(form: RatingForm, opts: { noRating?: boolean } = {}): Card {
  const card: Card = { change_goal: form.changeGoal };
  const from = parseClock(form.spanFrom);
  const to = parseClock(form.spanTo);
  if (from !== undefined && to !== undefined) card.coded_span = { from_s: from, to_s: to };
  if (opts.noRating) return card;

  const globals: NonNullable<Card["globals"]> = {};
  for (const g of GLOBALS) {
    const f = form.globals[g.id];
    const score = /^[1-5]$/.test(f.score) ? Number(f.score) : null;
    const at = parseClock(f.exTime);
    if (score === null && blank(f.reason) && blank(f.exText) && at === undefined) continue;
    const entry: NonNullable<Card["globals"]>[string] = { score };
    if (!blank(f.reason)) entry.reason = f.reason;
    if (!blank(f.exText) || at !== undefined) entry.example = { at_s: at ?? null, text: f.exText };
    globals[g.id] = entry;
  }
  if (Object.keys(globals).length) card.globals = globals;

  const counts: NonNullable<Card["counts"]> = {};
  for (const c of COUNTS) {
    const f = form.counts[c.id];
    const n = parseCount(f.count);
    if (n === undefined && blank(f.note)) continue;
    const entry: NonNullable<Card["counts"]>[string] = { count: n ?? null };
    if (!blank(f.note)) entry.note = f.note;
    counts[c.id] = entry;
  }
  if (Object.keys(counts).length) card.counts = counts;

  if (!blank(form.notes)) card.notes = form.notes;
  return card;
}

export function cardToForm(card: Card | undefined): RatingForm {
  const f = emptyForm();
  if (!card) return f;
  f.changeGoal = card.change_goal ?? "";
  if (card.coded_span && card.coded_span.from_s != null && card.coded_span.to_s != null) {
    f.spanFrom = formatClock(card.coded_span.from_s);
    f.spanTo = formatClock(card.coded_span.to_s);
  }
  for (const g of GLOBALS) {
    const s = card.globals?.[g.id];
    if (!s) continue;
    f.globals[g.id] = {
      score: s.score != null ? String(s.score) : "",
      reason: s.reason ?? "",
      exTime: s.example?.at_s != null ? formatClock(s.example.at_s) : "",
      exText: s.example?.text ?? "",
    };
  }
  for (const c of COUNTS) {
    const s = card.counts?.[c.id];
    if (s) f.counts[c.id] = { count: s.count != null ? String(s.count) : "", note: s.note ?? "" };
  }
  f.notes = card.notes ?? "";
  return f;
}

export type Issues = Record<string, string>;

/** Checks the form can fail before a final PUT. Keys are card paths (`globals.cct.example.at_s`). */
export function localIssues(form: RatingForm, opts: { noRating?: boolean } = {}): Issues {
  const out: Issues = {};
  if (blank(form.changeGoal)) out.change_goal = "Change goal is required.";
  const a = !blank(form.spanFrom);
  const b = !blank(form.spanTo);
  if (a || b) {
    const from = parseClock(form.spanFrom);
    const to = parseClock(form.spanTo);
    if (from === undefined || to === undefined) out.coded_span = "Enter both times as mm:ss, or leave both empty.";
    else if (from > to) out.coded_span = "The start must be before the end.";
  }
  if (opts.noRating) return out;
  for (const g of GLOBALS) {
    const f = form.globals[g.id];
    if (!blank(f.exTime) && parseClock(f.exTime) === undefined) out[`globals.${g.id}.example.at_s`] = "Use mm:ss.";
  }
  for (const c of COUNTS) {
    const f = form.counts[c.id];
    if (!blank(f.count) && parseCount(f.count) === undefined) out[`counts.${c.id}.count`] = "Enter a whole number, 0 or more.";
  }
  return out;
}

const fmt = (n: number) => n.toLocaleString("en-US");
const lengthMessage = (path: string) => `Too long: keep this to ${fmt(path === "notes" ? LIMITS.notes : LIMITS.item)} characters or fewer.`;

/**
 * Per-field messages from a 422 `rating_invalid`. Each detail is expected to start with a dotted
 * card path; the message is chosen locally, server text is never shown (no PHI, R8).
 */
export function issuesFromApi(err: ApiError): Issues {
  const out: Issues = {};
  for (const d of err.details) {
    const m = /^([a-z_]+(?:\.[a-z_0-9]+)*)\s(.*)$/.exec(d.message);
    if (!m) continue;
    const [, path, rest] = m;
    out[path] = /exceeds|too long/i.test(rest)
      ? lengthMessage(path)
      : /required/i.test(rest)
        ? "This is required."
        : /between 1 and 5/.test(rest)
          ? "Choose a score from 1 to 5."
          : /whole number/.test(rest)
            ? "Enter a whole number, 0 or more."
            : "Check this field.";
  }
  return out;
}
