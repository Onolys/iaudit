import { beforeEach, describe, expect, it } from "vitest";
import { createMemoryStatusEmitter, type SessionStatusDoc } from "../api/statusListener";
import type { SessionState } from "../api/types";
import { MockBackend, MockHttpError } from "./stateMachine";

const U = "u1";
const MP3 = { content_type: "audio/mpeg", size_bytes: 1_000_000, filename_ext: "mp3" };
const CARD = { change_goal: "Walk more in the evenings" };
const SCORED = {
  change_goal: "Walk more in the evenings",
  globals: { cct: { score: 4, reason: "Because" } },
};

function make(opts: { dailyCap?: number } = {}) {
  const emitter = createMemoryStatusEmitter();
  const backend = new MockBackend({ emitter, ...opts });
  const history: SessionStatusDoc[] = [];
  return { emitter, backend, history };
}

/** create -> upload -> complete (state validating). */
function started(b: MockBackend, title?: string, uid = U): string {
  const { session } = b.createSession(uid, { title });
  b.requestAudio(uid, session.id, MP3);
  b.completeAudio(uid, session.id);
  return session.id;
}

function status(b: MockBackend, sid: string, uid = U) {
  return b.getSession(uid, sid);
}

function expectHttp(fn: () => unknown, status: number, code: string) {
  try {
    fn();
    expect.unreachable("expected MockHttpError");
  } catch (e) {
    expect(e).toBeInstanceOf(MockHttpError);
    expect((e as MockHttpError).status).toBe(status);
    expect((e as MockHttpError).code).toBe(code);
  }
}

let ctx: ReturnType<typeof make>;
beforeEach(() => {
  ctx = make();
});

describe("happy path walks every state", () => {
  it("created -> uploading -> validating -> transcribing -> awaiting_input -> running -> report_ready -> deleting", () => {
    const { backend, emitter } = ctx;
    const seen: SessionState[] = [];
    const { session } = backend.createSession(U, {});
    const sid = session.id;
    emitter.subscribe(sid, (d) => d && seen.push(d.state), () => {});

    expect(status(backend, sid).status).toBe("created");
    backend.requestAudio(U, sid, MP3);
    expect(status(backend, sid).status).toBe("uploading");
    backend.completeAudio(U, sid);
    expect(status(backend, sid)).toMatchObject({ status: "validating", progress: 10 });

    backend.advance(sid);
    expect(status(backend, sid)).toMatchObject({ status: "transcribing", progress: 20 });

    backend.advance(sid);
    expect(status(backend, sid)).toMatchObject({
      status: "awaiting_input",
      progress: 40,
      flags: { transcript_ready: true, speaker_confirmed: false, rating_submitted: false },
    });

    backend.confirmSpeaker(U, sid, "spk_0");
    expect(status(backend, sid).status).toBe("awaiting_input");
    expect(status(backend, sid).flags.speaker_confirmed).toBe(true);

    backend.putRating(U, sid, { final: true, card: SCORED });
    expect(status(backend, sid)).toMatchObject({ status: "running", progress: 45, step: "paudit" });

    const progress: number[] = [];
    const steps: (string | null)[] = [];
    while (status(backend, sid).status === "running") {
      backend.advance(sid);
      progress.push(status(backend, sid).progress);
      steps.push(status(backend, sid).step ?? null);
    }
    expect(progress).toEqual([70, 85, 93, 97, 100]);
    expect(steps.slice(0, 4)).toEqual(["eaudit", "tips", "compare", "assemble"]);
    expect(status(backend, sid)).toMatchObject({
      status: "report_ready",
      latest_report_version: 1,
      progress: 100,
    });

    backend.deleteSession(U, sid);
    // first-occurrence order of the states a listener saw
    expect([...new Set(seen)]).toEqual([
      "created",
      "uploading",
      "validating",
      "transcribing",
      "awaiting_input",
      "running",
      "report_ready",
      "deleting",
    ]);
    expectHttp(() => backend.getSession(U, sid), 404, "not_found");
  });

  it("emits `failed` for a failing session (the ninth state)", () => {
    const { backend } = ctx;
    const sid = started(backend, "fail-no_speech");
    backend.settle(sid);
    expect(status(backend, sid).status).toBe("failed");
  });
});

describe("session_status mirror", () => {
  it("exists before createSession returns, with exactly the documented, PHI-free fields", () => {
    const { backend, emitter } = ctx;
    const { session } = backend.createSession(U, { title: "My private title" });
    const docs: SessionStatusDoc[] = [];
    emitter.subscribe(session.id, (d) => d && docs.push(d), () => {});
    expect(docs).toHaveLength(1);
    expect(Object.keys(docs[0]).sort()).toEqual(
      [
        "error_code",
        "has_rating",
        "latest_report_version",
        "progress",
        "rating_submitted",
        "speaker_confirmed",
        "state",
        "step",
        "transcript_ready",
        "uid",
        "updated_at",
      ].sort(),
    );
    expect(JSON.stringify(docs[0])).not.toContain("My private title");
  });

  it("never lets progress decrease within a run; a re-run restarts at 45", () => {
    const { backend, emitter } = ctx;
    const sid = started(backend);
    const progress: number[] = [];
    emitter.subscribe(sid, (d) => d && progress.push(d.progress), () => {});
    backend.settle(sid);
    backend.confirmSpeaker(U, sid, "spk_0");
    backend.putRating(U, sid, { final: true, card: SCORED });
    backend.settle(sid);
    for (let i = 1; i < progress.length; i++) expect(progress[i]).toBeGreaterThanOrEqual(progress[i - 1]);
    expect(progress.at(-1)).toBe(100);
    backend.startRun(U, sid, {});
    expect(status(backend, sid).progress).toBe(45);
  });
});

describe("first-run gate (any order, exactly one run)", () => {
  type Input = "rating" | "speaker" | "transcript";
  const orders: Input[][] = [
    ["rating", "transcript", "speaker"],
    ["transcript", "rating", "speaker"],
    ["transcript", "speaker", "rating"],
  ];
  it.each(orders)("%s, %s, %s", (...order) => {
    const { backend } = ctx;
    const sid = started(backend);
    // rating may arrive at any time, even before the transcript exists
    const apply = (i: Input) => {
      if (i === "rating") backend.putRating(U, sid, { final: true, card: SCORED });
      if (i === "speaker") backend.confirmSpeaker(U, sid, "spk_0");
      if (i === "transcript") backend.settle(sid);
    };
    order.forEach((i, idx) => {
      if (idx < 2) expect(status(backend, sid).status).not.toBe("running");
      apply(i);
    });
    expect(status(backend, sid).status).toBe("running");
    expect(backend.listRuns(U, sid)).toHaveLength(1);
  });

  it("accepts a rating while the file is still uploading and transcribing", () => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    backend.putRating(U, session.id, { final: true, card: CARD });
    expect(status(backend, session.id)).toMatchObject({
      status: "created",
      flags: { rating_submitted: true, has_rating: false },
    });
    backend.requestAudio(U, session.id, MP3);
    backend.completeAudio(U, session.id);
    backend.advance(session.id);
    expect(status(backend, session.id).status).toBe("transcribing");
    backend.putRating(U, session.id, { final: true, card: SCORED });
    expect(status(backend, session.id).flags.has_rating).toBe(true);
  });

  it("a draft never satisfies the gate", () => {
    const { backend } = ctx;
    const sid = started(backend);
    backend.settle(sid);
    backend.confirmSpeaker(U, sid, "spk_0");
    backend.putRating(U, sid, { final: false, card: SCORED });
    expect(status(backend, sid)).toMatchObject({
      status: "awaiting_input",
      flags: { rating_submitted: false, has_rating: false },
    });
  });

  it.each([
    ["no_rating: true", { final: true, no_rating: true, card: CARD }, false],
    ["a final card with no scores/counts/notes", { final: true, card: CARD }, false],
    ["a final card with scores", { final: true, card: SCORED }, true],
    ["a final card with only notes", { final: true, card: { ...CARD, notes: "context" } }, true],
  ])("%s sets has_rating correctly", (_name, body, hasRating) => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    backend.putRating(U, session.id, body);
    expect(status(backend, session.id).flags).toMatchObject({
      rating_submitted: true,
      has_rating: hasRating,
    });
  });

  it("cannot confirm a speaker before the transcript is ready", () => {
    const { backend } = ctx;
    const sid = started(backend);
    expectHttp(() => backend.confirmSpeaker(U, sid, "spk_0"), 409, "invalid_state");
  });

  it("rejects an unknown speaker id", () => {
    const { backend } = ctx;
    const sid = started(backend);
    backend.settle(sid);
    expectHttp(() => backend.confirmSpeaker(U, sid, "nobody"), 422, "invalid_parameters");
  });
});

describe("awaiting_input flags", () => {
  it("lists what is missing: speaker only, rating only, both", () => {
    const { backend } = ctx;
    const both = started(backend);
    backend.settle(both);
    expect(status(backend, both).flags).toEqual({
      transcript_ready: true,
      speaker_confirmed: false,
      rating_submitted: false,
      has_rating: false,
    });

    const noSpeaker = started(backend);
    backend.putRating(U, noSpeaker, { final: true, card: SCORED });
    backend.settle(noSpeaker);
    expect(status(backend, noSpeaker)).toMatchObject({
      status: "awaiting_input",
      flags: { speaker_confirmed: false, rating_submitted: true },
    });

    const noRating = started(backend);
    backend.settle(noRating);
    backend.confirmSpeaker(U, noRating, "spk_0");
    expect(status(backend, noRating)).toMatchObject({
      status: "awaiting_input",
      flags: { speaker_confirmed: true, rating_submitted: false },
    });
  });
});

describe("failure injection by title", () => {
  it.each([
    ["fail-audio_unreadable", "validate", "audio_unreadable"],
    ["fail-unsupported_audio", "validate", "unsupported_audio"],
    ["fail-no_speech", "transcribe", "no_speech"],
    ["fail-speakers_not_separated", "transcribe", "speakers_not_separated"],
    ["fail-transcription_failed", "transcribe", "transcription_failed"],
  ])("%s fails at %s with %s", (title, step, code) => {
    const { backend } = ctx;
    const sid = started(backend, title);
    backend.settle(sid);
    expect(status(backend, sid)).toMatchObject({
      status: "failed",
      error: { code, step },
      flags: { transcript_ready: false },
    });
    expectHttp(() => backend.startRun(U, sid, {}), 409, "invalid_state");
  });

  function ready(title: string) {
    const { backend } = ctx;
    const sid = started(backend, title);
    backend.settle(sid);
    backend.confirmSpeaker(U, sid, "spk_0");
    backend.putRating(U, sid, { final: true, card: SCORED });
    backend.settle(sid);
    return { backend, sid };
  }

  it("fail-paudit fails the run and the session (can Run again)", () => {
    const { backend, sid } = ready("fail-paudit");
    expect(status(backend, sid)).toMatchObject({ status: "failed", error: { code: "internal_error", step: "paudit" } });
    expect(status(backend, sid).latest_report_version).toBeNull();
    backend.startRun(U, sid, {}); // later failures offer Run again
    expect(status(backend, sid).status).toBe("running");
  });

  it("fail-eaudit still produces a report with reasons_audit failed + warning", () => {
    const { backend, sid } = ready("fail-eaudit");
    expect(status(backend, sid).status).toBe("report_ready");
    const r = backend.getReport(U, sid, 1);
    expect(r.reasons_audit.status).toBe("failed");
    expect(r.warnings.map((w) => w.code)).toContain("reasons_audit_failed");
    expect(r.tips.length).toBeGreaterThan(0);
  });

  it("fail-tips produces a report with no tips + warning", () => {
    const { backend, sid } = ready("fail-tips");
    const r = backend.getReport(U, sid, 1);
    expect(r.tips).toEqual([]);
    expect(r.warnings.map((w) => w.code)).toContain("tips_failed");
  });
});

describe("daily cap", () => {
  it("cap-held: auto-start is held (awaiting_input + error_code) and Start runs it", () => {
    const { backend } = ctx;
    const sid = started(backend, "cap-held");
    backend.settle(sid);
    backend.confirmSpeaker(U, sid, "spk_0");
    backend.putRating(U, sid, { final: true, card: SCORED });
    expect(status(backend, sid)).toMatchObject({
      status: "awaiting_input",
      error: { code: "daily_cap_reached" },
    });
    expect(backend.listRuns(U, sid)).toHaveLength(0);
    backend.startRun(U, sid, {});
    expect(status(backend, sid)).toMatchObject({ status: "running" });
    expect(status(backend, sid).error).toBeUndefined();
  });

  it("a real cap: POST /runs over the cap is 429 daily_cap_reached; usage reports it", () => {
    const { backend } = make({ dailyCap: 1 });
    const sid = started(backend);
    backend.settle(sid);
    backend.confirmSpeaker(U, sid, "spk_0");
    backend.putRating(U, sid, { final: true, card: SCORED });
    backend.settle(sid);
    expect(backend.getUsage(U)).toMatchObject({ runs_today: 1, daily_cap: 1 });
    expectHttp(() => backend.startRun(U, sid, {}), 429, "daily_cap_reached");
  });

  it("the auto-start also stops at a real cap", () => {
    const { backend } = make({ dailyCap: 0 });
    const sid = started(backend);
    backend.settle(sid);
    backend.confirmSpeaker(U, sid, "spk_0");
    backend.putRating(U, sid, { final: true, card: SCORED });
    expect(status(backend, sid).error).toEqual({ code: "daily_cap_reached" });
  });
});

describe("re-runs and report versions", () => {
  function reported(rating: object) {
    const { backend } = ctx;
    const sid = started(backend);
    backend.settle(sid);
    backend.confirmSpeaker(U, sid, "spk_0");
    backend.putRating(U, sid, rating as never);
    backend.settle(sid);
    return { backend, sid };
  }

  it("Run again creates v2 and keeps v1", () => {
    const { backend, sid } = reported({ final: true, card: SCORED });
    backend.startRun(U, sid, {});
    expect(status(backend, sid).status).toBe("running");
    backend.settle(sid);
    expect(backend.listReports(U, sid).map((r) => r.version)).toEqual([1, 2]);
    expect(backend.getReport(U, sid, 1).header.has_clinician_rating).toBe(true);
    expect(status(backend, sid).latest_report_version).toBe(2);
  });

  it("no-rating run, then add a rating and run again gives a rated v2", () => {
    const { backend, sid } = reported({ final: true, no_rating: true, card: CARD });
    const v1 = backend.getReport(U, sid, 1);
    expect(v1.header.has_clinician_rating).toBe(false);
    expect(v1.reasons_audit.status).toBe("skipped");
    backend.putRating(U, sid, { final: true, card: SCORED }); // allowed in report_ready
    backend.startRun(U, sid, {});
    backend.settle(sid);
    expect(backend.getReport(U, sid, 2).header.has_clinician_rating).toBe(true);
    expect(backend.getReport(U, sid, 1).header.has_clinician_rating).toBe(false);
  });

  it("run records carry stt, preset, code_version and the rating snapshot", () => {
    const { backend, sid } = reported({ final: true, card: SCORED });
    const [run] = backend.listRuns(U, sid);
    expect(run).toMatchObject({ status: "done", n_runs: 1 });
    expect(run.rating_id).toBeTruthy();
    expect(run.code_version).toBeTruthy();
    expect(run.stt?.provider).toBeTruthy();
    expect(backend.getRun(U, run.run_id).run_id).toBe(run.run_id);
  });

  it("a re-run in report_ready needs no new transcript; a run while running is 409", () => {
    const { backend, sid } = reported({ final: true, card: SCORED });
    backend.startRun(U, sid, {});
    expectHttp(() => backend.startRun(U, sid, {}), 409, "invalid_state");
  });

  it("changing the clinician in report_ready applies to the next run only", () => {
    const { backend, sid } = reported({ final: true, card: SCORED });
    backend.confirmSpeaker(U, sid, "spk_1");
    expect(status(backend, sid).status).toBe("report_ready");
    expect(backend.getTranscript(U, sid).clinician_speaker).toBe("spk_1");
    expect(backend.listReports(U, sid)).toHaveLength(1);
  });

  it("unknown report version is 404", () => {
    const { backend, sid } = reported({ final: true, card: SCORED });
    expectHttp(() => backend.getReport(U, sid, 9), 404, "not_found");
  });
});

describe("rating draft vs final", () => {
  it("GET returns the draft only when newer than the last final", () => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    const sid = session.id;
    expect(backend.getRating(U, sid)).toEqual({});
    backend.putRating(U, sid, { final: false, card: { change_goal: "draft goal" } });
    expect(backend.getRating(U, sid).draft?.card.change_goal).toBe("draft goal");
    expect(backend.getRating(U, sid).final).toBeUndefined();
    backend.putRating(U, sid, { final: true, card: CARD });
    expect(backend.getRating(U, sid).draft).toBeUndefined();
    expect(backend.getRating(U, sid).final?.card.change_goal).toBe(CARD.change_goal);
    backend.putRating(U, sid, { final: false, card: { change_goal: "newer" } });
    expect(backend.getRating(U, sid).draft?.card.change_goal).toBe("newer");
    expect(backend.getRating(U, sid).final).toBeDefined();
  });

  it("each final PUT is a new revision", () => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    const a = backend.putRating(U, session.id, { final: true, card: CARD });
    const b = backend.putRating(U, session.id, { final: true, card: SCORED });
    expect(a.rating_id).toBeTruthy();
    expect(b.rating_id).not.toBe(a.rating_id);
  });

  it.each([
    ["reason > 1000", { final: true, card: { change_goal: "g", globals: { cct: { reason: "x".repeat(1001) } } } }, "globals.cct.reason"],
    ["example text > 1000", { final: true, card: { change_goal: "g", globals: { cct: { example: { at_s: 3, text: "x".repeat(1001) } } } } }, "globals.cct.example.text"],
    ["code note > 1000", { final: true, card: { change_goal: "g", counts: { sr: { note: "x".repeat(1001) } } } }, "counts.sr.note"],
    ["notes > 3000", { final: true, card: { change_goal: "g", notes: "x".repeat(3001) } }, "notes"],
    ["missing change_goal on final", { final: true, card: {} }, "change_goal"],
    ["score out of range", { final: true, card: { change_goal: "g", globals: { cct: { score: 6 } } } }, "globals.cct.score"],
  ])("final with %s is 422 rating_invalid naming the field", (_n, body, field) => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    try {
      backend.putRating(U, session.id, body as never);
      expect.unreachable();
    } catch (e) {
      const err = e as MockHttpError;
      expect(err.status).toBe(422);
      expect(err.details.every((d) => d.code === "rating_invalid")).toBe(true);
      expect(err.details.map((d) => d.field)).toContain(field.replaceAll(".", "/"));
      expect(err.details.every((d) => typeof d.issue === "string")).toBe(true);
    }
  });

  it("a draft over a hard limit is rejected too, but a draft without change_goal is fine", () => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    backend.putRating(U, session.id, { final: false, card: {} });
    expectHttp(
      () => backend.putRating(U, session.id, { final: false, card: { notes: "x".repeat(3001) } }),
      422,
      "rating_invalid",
    );
  });

  it("is rejected only in deleting (session is gone afterwards)", () => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    backend.deleteSession(U, session.id);
    expectHttp(() => backend.putRating(U, session.id, { final: true, card: CARD }), 404, "not_found");
  });
});

describe("validation of upload calls", () => {
  it.each([
    ["audio/mpeg", "mp3", "audio/mpeg"],
    ["audio/x-m4a", "m4a", "audio/mp4"],
    ["audio/mp4", "m4a", "audio/mp4"],
    ["", "m4a", "audio/mp4"],
    ["", "wav", "audio/wav"],
    ["audio/x-wav", "wav", "audio/wav"],
  ])("maps %j + .%s to canonical %s in required_headers", (content_type, filename_ext, canonical) => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    const r = backend.requestAudio(U, session.id, { content_type, size_bytes: 10, filename_ext });
    expect(r.required_headers["Content-Type"]).toBe(canonical);
    expect(r.required_headers["x-goog-content-length-range"]).toBe("0,314572800");
    expect(r.upload_url).toContain(r.upload_id);
  });

  it("422 unsupported_audio for an unknown type and 422 audio_too_large over 300 MB", () => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    expectHttp(
      () => backend.requestAudio(U, session.id, { content_type: "video/mp4", size_bytes: 10, filename_ext: "mp4" }),
      422,
      "unsupported_audio",
    );
    expectHttp(
      () => backend.requestAudio(U, session.id, { ...MP3, size_bytes: 300 * 1024 * 1024 + 1 }),
      422,
      "audio_too_large",
    );
  });

  it("409 invalid_state: complete before audio, audio after validation started", () => {
    const { backend } = ctx;
    const { session } = backend.createSession(U, {});
    expectHttp(() => backend.completeAudio(U, session.id), 409, "invalid_state");
    backend.requestAudio(U, session.id, MP3);
    backend.requestAudio(U, session.id, MP3); // fresh URL while still uploading is fine
    backend.completeAudio(U, session.id);
    expectHttp(() => backend.requestAudio(U, session.id, MP3), 409, "invalid_state");
  });

  it("409 invalid_state: transcript before transcription finishes", () => {
    const { backend } = ctx;
    const sid = started(backend);
    expectHttp(() => backend.getTranscript(U, sid), 409, "invalid_state");
  });
});

describe("transcript and speaker fixtures", () => {
  it("lists 3 sample lines per speaker; role is null until confirmed", () => {
    const { backend } = ctx;
    const sid = started(backend);
    backend.settle(sid);
    const sp = backend.getSpeakers(U, sid);
    expect(sp.speakers.map((s) => s.speaker)).toEqual(["spk_0", "spk_1"]);
    for (const s of sp.speakers) expect(s.samples).toHaveLength(3);
    expect(backend.getTranscript(U, sid).turns.every((t) => t.role === null)).toBe(true);
    backend.confirmSpeaker(U, sid, "spk_0");
    const turns = backend.getTranscript(U, sid).turns;
    expect(turns.find((t) => t.speaker === "spk_0")?.role).toBe("clinician");
    expect(turns.find((t) => t.speaker === "spk_1")?.role).toBe("client");
  });

  it("three-speakers title yields a 3-speaker gate", () => {
    const { backend } = ctx;
    const sid = started(backend, "three-speakers");
    backend.settle(sid);
    const sp = backend.getSpeakers(U, sid);
    expect(sp.speakers).toHaveLength(3);
    for (const s of sp.speakers) expect(s.samples).toHaveLength(3);
  });

  it("utf8-edge title serves the UTF-8 edge transcript", () => {
    const { backend } = ctx;
    const sid = started(backend, "utf8-edge");
    backend.settle(sid);
    const text = backend.getTranscript(U, sid).turns.map((t) => t.text).join(" ");
    expect(text).toMatch(/\p{Extended_Pictographic}/u);
  });
});

describe("tenancy, list, delete, idempotency", () => {
  it("another user gets 404 on every id", () => {
    const { backend } = ctx;
    const sid = started(backend);
    backend.settle(sid);
    expectHttp(() => backend.getSession("u2", sid), 404, "not_found");
    expectHttp(() => backend.getTranscript("u2", sid), 404, "not_found");
    expectHttp(() => backend.deleteSession("u2", sid), 404, "not_found");
    expectHttp(() => backend.putRating("u2", sid, { final: false, card: {} }), 404, "not_found");
    expect(backend.listSessions("u2", {}).items).toEqual([]);
  });

  it("lists newest first with cursor paging, in every state", () => {
    const { backend } = ctx;
    const ids = [1, 2, 3].map(() => backend.createSession(U, {}).session.id);
    const page1 = backend.listSessions(U, { limit: 2 });
    expect(page1.items.map((i) => i.id)).toEqual([ids[2], ids[1]]);
    expect(page1.next_cursor).toBeTruthy();
    const page2 = backend.listSessions(U, { limit: 2, cursor: page1.next_cursor ?? undefined });
    expect(page2.items.map((i) => i.id)).toEqual([ids[0]]);
    expect(page2.next_cursor).toBeUndefined();
    expect(page1.items[0]).toMatchObject({ status: "created", latest_report_version: null, error_code: null });
  });

  it("delete removes the session and its status doc", () => {
    const { backend, emitter } = ctx;
    const { session } = backend.createSession(U, {});
    let last: SessionStatusDoc | null | undefined;
    emitter.subscribe(session.id, (d) => (last = d), () => {});
    backend.deleteSession(U, session.id);
    expect(last).toBeNull();
    expect(backend.listSessions(U, {}).items).toEqual([]);
  });

  it("Idempotency-Key: same key+body returns the original; different body is 409 conflict", () => {
    const { backend } = ctx;
    const a = backend.createSession(U, { title: "a" }, "k1");
    const b = backend.createSession(U, { title: "a" }, "k1");
    expect(b.session.id).toBe(a.session.id);
    expect(backend.listSessions(U, {}).items).toHaveLength(1);
    expectHttp(() => backend.createSession(U, { title: "different" }, "k1"), 409, "conflict");
  });

  it("validates create params", () => {
    const { backend } = ctx;
    expectHttp(() => backend.createSession(U, { n_runs: 9 }), 422, "invalid_parameters");
    expectHttp(() => backend.createSession(U, { preset: "nope" }), 422, "invalid_parameters");
  });
});
