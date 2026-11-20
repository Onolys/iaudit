import { describe, expect, it } from "vitest";
import type { SessionState } from "../../api/schema";
import { deriveTimeline, STEP_LABELS } from "./timeline";

const STATES: SessionState[] = [
  "created",
  "uploading",
  "validating",
  "transcribing",
  "awaiting_input",
  "running",
  "report_ready",
  "failed",
  "deleting",
];

interface Flags {
  transcript_ready: boolean;
  speaker_confirmed: boolean;
  rating_submitted: boolean;
}
const none: Flags = { transcript_ready: false, speaker_confirmed: false, rating_submitted: false };
const T = { transcript_ready: true };
const S = { speaker_confirmed: true };
const R = { rating_submitted: true };

// Steps: upload, validate, transcribe, speaker, rating, run, report.
// d = done, c = current, p = pending, f = failed.
type Row = [
  name: string,
  state: SessionState,
  flags: Partial<Flags>,
  extra: { step?: string | null; error_code?: string | null },
  statuses: string,
  lines: string[],
];

const ROWS: Row[] = [
  ["created", "created", {}, {}, "cpppppp", ["Getting ready to upload your recording."]],
  ["created, rating already filled", "created", R, {}, "cpppdpp", ["Getting ready to upload your recording."]],
  ["uploading", "uploading", {}, {}, "cpppppp", ["Uploading your recording."]],
  ["validating", "validating", {}, {}, "dcppppp", ["Checking your audio."]],
  ["validating, rating filled early", "validating", R, {}, "dcppdpp", ["Checking your audio."]],
  ["transcribing", "transcribing", {}, {}, "ddcpppp", ["Transcribing the recording."]],
  ["transcribing, rating filled early", "transcribing", R, {}, "ddcpdpp", ["Transcribing the recording."]],
  [
    "awaiting_input: speaker and rating missing",
    "awaiting_input",
    T,
    {},
    "dddccpp",
    ["Confirm who the clinician is", "Waiting for your rating"],
  ],
  ["awaiting_input: speaker missing", "awaiting_input", { ...T, ...R }, {}, "dddcdpp", ["Confirm who the clinician is"]],
  ["awaiting_input: rating missing", "awaiting_input", { ...T, ...S }, {}, "ddddcpp", ["Waiting for your rating"]],
  ["awaiting_input: all in, starting", "awaiting_input", { ...T, ...S, ...R }, {}, "dddddpp", ["Starting the rating."]],
  [
    "awaiting_input: cap reached",
    "awaiting_input",
    { ...T, ...S, ...R },
    { error_code: "daily_cap_reached" },
    "dddddpp",
    ["You've reached today's limit. You can start the rating after 9:00 AM."],
  ],
  ["running, paudit", "running", { ...T, ...S, ...R }, { step: "paudit" }, "dddddcp", ["Rating the session"]],
  ["running, eaudit", "running", { ...T, ...S, ...R }, { step: "eaudit" }, "dddddcp", ["Checking your reasons"]],
  ["running, tips", "running", { ...T, ...S, ...R }, { step: "tips" }, "dddddcp", ["Writing tips"]],
  ["running, compare", "running", { ...T, ...S, ...R }, { step: "compare" }, "dddddcp", ["Comparing"]],
  ["running, assemble", "running", { ...T, ...S, ...R }, { step: "assemble" }, "dddddcp", ["Building the report"]],
  ["running, no step yet", "running", { ...T, ...S, ...R }, { step: null }, "dddddcp", ["Rating the session"]],
  ["running, unknown step", "running", { ...T, ...S, ...R }, { step: "zzz" }, "dddddcp", ["Rating the session"]],
  ["report_ready", "report_ready", { ...T, ...S, ...R }, {}, "ddddddd", ["Your report is ready."]],
  [
    "failed at validate",
    "failed",
    {},
    { error_code: "audio_unreadable" },
    "dfppppp",
    ["This session couldn't be completed."],
  ],
  [
    "failed at transcribe",
    "failed",
    {},
    { error_code: "no_speech" },
    "ddfpppp",
    ["This session couldn't be completed."],
  ],
  [
    "failed at transcribe (speakers_not_separated)",
    "failed",
    {},
    { error_code: "speakers_not_separated" },
    "ddfpppp",
    ["This session couldn't be completed."],
  ],
  [
    "failed during run",
    "failed",
    { ...T, ...S, ...R },
    { error_code: "internal_error", step: null },
    "dddddfp",
    ["This session couldn't be completed."],
  ],
  [
    "failed during run, rating missing",
    "failed",
    { ...T, ...S },
    { error_code: "upstream_unavailable" },
    "ddddpfp",
    ["This session couldn't be completed."],
  ],
  ["deleting", "deleting", { ...T, ...S, ...R }, {}, "ppppppp", ["Deleting this session."]],
];

describe("deriveTimeline: table", () => {
  it.each(ROWS)("%s", (_name, state, flags, extra, statuses, lines) => {
    const t = deriveTimeline(
      { state, step: extra.step ?? null, error_code: extra.error_code ?? null, ...none, ...flags },
      { resetsAt: "9:00 AM" },
    );
    expect(t.steps.map((s) => s.key)).toEqual([
      "upload",
      "validate",
      "transcribe",
      "speaker",
      "rating",
      "run",
      "report",
    ]);
    expect(t.steps.map((s) => s.label)).toEqual([
      "Upload",
      "Check audio",
      "Transcribe",
      "Confirm speaker",
      "Your rating",
      "Rate session",
      "Report",
    ]);
    expect(t.steps.map((s) => s.status[0]).join("")).toBe(statuses);
    expect(t.lines).toEqual(lines);
  });

  it("keeps the label list in step order", () => {
    expect(STEP_LABELS).toEqual([
      "Upload",
      "Check audio",
      "Transcribe",
      "Confirm speaker",
      "Your rating",
      "Rate session",
      "Report",
    ]);
  });
});

describe("deriveTimeline: every state x flag combination", () => {
  const bools = [false, true];
  const combos = STATES.flatMap((state) =>
    bools.flatMap((t) =>
      bools.flatMap((s) =>
        bools.map((r) => ({ state, transcript_ready: t, speaker_confirmed: s, rating_submitted: r })),
      ),
    ),
  );

  it.each(combos)("%o has coherent steps and copy", (c) => {
    const t = deriveTimeline({ ...c, step: null, error_code: null });
    expect(t.steps).toHaveLength(7);
    expect(t.lines.length).toBeGreaterThan(0);
    expect(t.lines.every((l) => l.trim().length > 0)).toBe(true);
    const byKey = Object.fromEntries(t.steps.map((s) => [s.key, s.status]));
    // Gates derive from the flags alone, never from a per-gate state.
    if (c.state !== "deleting") {
      if (c.speaker_confirmed) expect(byKey.speaker).toBe("done");
      if (c.rating_submitted) expect(byKey.rating).toBe("done");
    }
    if (c.state === "report_ready") expect(byKey.report).toBe("done");
    if (c.state !== "report_ready") expect(byKey.report).toBe("pending");
    expect(t.steps.filter((s) => s.status === "failed")).toHaveLength(c.state === "failed" ? 1 : 0);
    const copy = t.lines.join(" ");
    if (c.state === "awaiting_input") {
      expect(copy.includes("Confirm who the clinician is")).toBe(!c.speaker_confirmed);
      expect(copy.includes("Waiting for your rating")).toBe(!c.rating_submitted);
    }
  });
});

describe("deriveTimeline: extras", () => {
  const base = { state: "running" as const, step: "eaudit", error_code: null, ...none, ...T, ...S, ...R };

  it("puts the sub-label from step on the running step only", () => {
    const t = deriveTimeline(base);
    expect(t.steps.find((s) => s.key === "run")?.subLabel).toBe("Checking your reasons");
    expect(t.steps.filter((s) => s.subLabel)).toHaveLength(1);
  });

  it("shows the 'close this tab' copy once the run has started and not before", () => {
    expect(deriveTimeline(base).showRunCopy).toBe(true);
    expect(deriveTimeline({ ...base, state: "transcribing" }).showRunCopy).toBe(false);
    expect(deriveTimeline({ ...base, state: "report_ready" }).showRunCopy).toBe(false);
  });

  it("flags the cap message with a Start action", () => {
    const t = deriveTimeline({ ...base, state: "awaiting_input", error_code: "daily_cap_reached" });
    expect(t.capReached).toBe(true);
    expect(t.lines[0]).toBe("You've reached today's limit.");
  });

  it("does not offer Start for a cap code outside awaiting_input", () => {
    expect(deriveTimeline({ ...base, state: "failed", error_code: "daily_cap_reached" }).capReached).toBe(false);
  });
});
