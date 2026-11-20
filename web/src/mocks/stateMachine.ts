/**
 * In-memory mock of the SP04 API (PRD R4/R7, D5). Pure TypeScript, no MSW and
 * no timers: HTTP handlers call it, tests drive it with `advance`/`settle`, and
 * the browser worker advances it on an interval. Every state change is mirrored
 * to a PHI-free `session_status` doc through the status emitter.
 */
import type { Report } from "../api/report";
import type { components, RunStage, SessionState } from "../api/schema";
import type { MemoryStatusEmitter, SessionStatusDoc } from "../api/statusListener";
import {
  edgeTranscript,
  reportFor,
  sampleLines,
  sampleTranscript,
  threeSpeakerTranscript,
  type Turn,
} from "./fixtures";

type S = components["schemas"];

export class MockHttpError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: S["ErrorDetail"][];
  constructor(status: number, code: string, message: string, details?: S["ErrorDetail"][]) {
    super(message);
    this.name = "MockHttpError";
    this.status = status;
    this.code = code;
    this.details = details ?? [{ code, message }];
  }
}

export interface MockOptions {
  emitter: MemoryStatusEmitter;
  dailyCap?: number;
  now?: () => Date;
}

const MAX_AUDIO_BYTES = 300 * 1024 * 1024;
const PRESETS = ["default", "fast"];
const STAGES: RunStage[] = ["paudit", "eaudit", "tips", "compare", "assemble"];
/** SP04 R4 progress table: weights added as each stage finishes. */
const STAGE_WEIGHT: Record<RunStage, number> = { paudit: 25, eaudit: 15, tips: 8, compare: 4, assemble: 3 };
const RUN_START_PROGRESS = 45;

const CANONICAL: Record<string, { ext: string; types: string[]; canonical: string }> = {
  mp3: { ext: "mp3", types: ["audio/mpeg", "audio/mp3"], canonical: "audio/mpeg" },
  wav: { ext: "wav", types: ["audio/wav", "audio/x-wav", "audio/wave"], canonical: "audio/wav" },
  m4a: { ext: "m4a", types: ["audio/mp4", "audio/x-m4a", "audio/m4a"], canonical: "audio/mp4" },
  webm: { ext: "webm", types: ["audio/webm"], canonical: "audio/webm" },
  ogg: { ext: "ogg", types: ["audio/ogg", "application/ogg"], canonical: "audio/ogg" },
};

/** Failure injection by magic session title (like the SP04 fake adapters). */
const VALIDATE_FAILS = ["audio_unreadable", "unsupported_audio", "audio_too_long", "audio_too_large"];
const TRANSCRIBE_FAILS = ["no_speech", "speakers_not_separated", "transcription_failed"];

interface Rating {
  rating_id: string;
  no_rating: boolean;
  has_content: boolean;
  card: S["RatingCard"];
  seq: number;
}

type RunRec = S["Run"] & { stageIdx: number };

interface ReportRec {
  version: number;
  report_id: string;
  run_id: string;
  created_at: string;
  report: Report;
}

interface SessionRec {
  id: string;
  uid: string;
  seq: number;
  title: string | null;
  language: string;
  n_runs: number;
  preset: string;
  created_at: string;
  state: SessionState;
  step: string | null;
  progress: number;
  error: { code: string; step?: string } | null;
  flags: S["SessionFlags"];
  clinician_speaker: string | null;
  first_run_id: string | null;
  holdFirstStart: boolean;
  uploadId: string | null;
  uploadType: string | null;
  finals: Rating[];
  draft: { card: S["RatingCard"]; updated_at: string; seq: number } | null;
  runs: RunRec[];
  reports: ReportRec[];
}

function bad(status: number, code: string, message: string, details?: S["ErrorDetail"][]): never {
  throw new MockHttpError(status, code, message, details);
}

const notFound = () => bad(404, "not_found", "Not found.");

function invalidParam(message: string): never {
  return bad(422, "invalid_parameters", message);
}

export class MockBackend {
  private readonly emitter: MemoryStatusEmitter;
  private readonly now: () => Date;
  private readonly initialCap: number;
  private dailyCap: number;
  private sessions = new Map<string, SessionRec>();
  private runsByDay = new Map<string, number>();
  private idem = new Map<string, { hash: string; response: S["CreateSessionResponse"] }>();
  private n = 0;

  constructor(opts: MockOptions) {
    this.emitter = opts.emitter;
    this.now = opts.now ?? (() => new Date());
    this.initialCap = this.dailyCap = opts.dailyCap ?? 20;
  }

  /** Drop all data and restore options (used between tests). */
  reset(): void {
    this.sessions.clear();
    this.runsByDay.clear();
    this.idem.clear();
    this.n = 0;
    this.dailyCap = this.initialCap;
    this.emitter.clear();
  }

  configure(o: { dailyCap?: number }): void {
    if (o.dailyCap !== undefined) this.dailyCap = o.dailyCap;
  }

  // ---- helpers ------------------------------------------------------------

  private id(prefix: string): string {
    this.n += 1;
    return `${prefix}_${this.n}`;
  }

  private own(uid: string, sid: string): SessionRec {
    const s = this.sessions.get(sid);
    if (!s || s.uid !== uid) notFound();
    return s as SessionRec;
  }

  private emit(s: SessionRec): void {
    const doc: SessionStatusDoc = {
      uid: s.uid,
      state: s.state,
      step: s.step,
      progress: s.progress,
      error_code: s.error?.code ?? null,
      latest_report_version: s.reports.at(-1)?.version ?? null,
      updated_at: this.now().toISOString(),
      ...s.flags,
    };
    this.emitter.emit(s.id, doc);
  }

  private dayKey(uid: string): string {
    return `${uid}:${this.now().toISOString().slice(0, 10)}`;
  }

  private runsToday(uid: string): number {
    return this.runsByDay.get(this.dayKey(uid)) ?? 0;
  }

  private titleIs(s: SessionRec, name: string): boolean {
    return (s.title ?? "").trim().toLowerCase() === name;
  }

  private injected(s: SessionRec, codes: string[]): string | undefined {
    return codes.find((c) => this.titleIs(s, `fail-${c}`));
  }

  private turns(s: SessionRec): Turn[] {
    if (this.titleIs(s, "utf8-edge")) return edgeTranscript;
    if (this.titleIs(s, "three-speakers")) return threeSpeakerTranscript;
    return sampleTranscript;
  }

  private fail(s: SessionRec, code: string, step: string): void {
    s.state = "failed";
    s.error = { code, step };
    s.step = null;
    this.emit(s);
  }

  // ---- sessions -----------------------------------------------------------

  createSession(
    uid: string,
    body: S["CreateSessionRequest"],
    idempotencyKey?: string,
  ): S["CreateSessionResponse"] {
    if (body.language !== undefined && body.language !== "auto" && !/^[a-z]{2,3}(-[A-Z]{2})?$/.test(body.language))
      invalidParam("language is not a valid BCP-47 tag or auto");
    if (body.n_runs !== undefined && (!Number.isInteger(body.n_runs) || body.n_runs < 1 || body.n_runs > 5))
      invalidParam("n_runs must be an integer from 1 to 5");
    if (body.preset !== undefined && !PRESETS.includes(body.preset)) invalidParam("preset is not allowed");
    if (body.title != null && (typeof body.title !== "string" || body.title.length > 200))
      invalidParam("title is too long");

    const idemKey = idempotencyKey ? `${uid}:${idempotencyKey}` : null;
    const hash = JSON.stringify(body);
    if (idemKey) {
      const prior = this.idem.get(idemKey);
      if (prior) {
        if (prior.hash !== hash) bad(409, "conflict", "Idempotency-Key reused with a different body.");
        return prior.response;
      }
    }

    const seq = this.n + 1;
    const id = this.id("s");
    const s: SessionRec = {
      id,
      uid,
      seq,
      title: body.title ?? null,
      language: body.language ?? "auto",
      n_runs: body.n_runs ?? 1,
      preset: body.preset ?? "default",
      created_at: this.now().toISOString(),
      state: "created",
      step: null,
      progress: 0,
      error: null,
      flags: { transcript_ready: false, speaker_confirmed: false, rating_submitted: false, has_rating: false },
      clinician_speaker: null,
      first_run_id: null,
      holdFirstStart: false,
      uploadId: null,
      uploadType: null,
      finals: [],
      draft: null,
      runs: [],
      reports: [],
    };
    s.holdFirstStart = this.titleIs(s, "cap-held");
    this.sessions.set(id, s);
    this.emit(s); // before returning, so a listener can attach at once
    const response = { session: { id, status: s.state } };
    if (idemKey) this.idem.set(idemKey, { hash, response });
    return response;
  }

  listSessions(uid: string, q: { limit?: number; cursor?: string }): S["SessionList"] {
    const limit = Math.min(Math.max(q.limit ?? 20, 1), 50);
    const offset = q.cursor ? Number.parseInt(q.cursor, 10) || 0 : 0;
    const all = [...this.sessions.values()].filter((s) => s.uid === uid).sort((a, b) => b.seq - a.seq);
    const items = all.slice(offset, offset + limit).map((s) => ({
      id: s.id,
      title: s.title,
      status: s.state,
      created_at: s.created_at,
      latest_report_version: s.reports.at(-1)?.version ?? null,
      error_code: s.error?.code ?? null,
    }));
    const next = offset + limit;
    return next < all.length ? { items, next_cursor: String(next) } : { items };
  }

  getSession(uid: string, sid: string): S["SessionDetail"] {
    const s = this.own(uid, sid);
    const detail: S["SessionDetail"] = {
      id: s.id,
      title: s.title,
      status: s.state,
      step: s.step,
      progress: s.progress,
      flags: { ...s.flags },
      warnings: [],
      latest_report_version: s.reports.at(-1)?.version ?? null,
    };
    if (s.error) detail.error = { ...s.error };
    return detail;
  }

  deleteSession(uid: string, sid: string): void {
    const s = this.own(uid, sid);
    s.state = "deleting";
    this.emit(s);
    this.sessions.delete(sid);
    this.emitter.remove(sid);
  }

  // ---- audio --------------------------------------------------------------

  requestAudio(uid: string, sid: string, body: S["AudioUploadRequest"]): S["AudioUploadResponse"] {
    const s = this.own(uid, sid);
    if (s.state !== "created" && s.state !== "uploading") bad(409, "invalid_state", "Audio can no longer be uploaded.");
    const ext = (body.filename_ext ?? "").replace(/^\./, "").toLowerCase();
    const type = (body.content_type ?? "").toLowerCase();
    const byType = Object.values(CANONICAL).find((f) => f.types.includes(type));
    const byExt = CANONICAL[ext];
    const format = type === "" ? byExt : byType;
    if (!format) bad(422, "unsupported_audio", "Unsupported audio type.");
    if (!(body.size_bytes >= 0) || body.size_bytes > MAX_AUDIO_BYTES)
      bad(422, "audio_too_large", "Audio file is too large.");

    s.uploadId = this.id("up");
    s.uploadType = format.canonical;
    s.state = "uploading";
    s.step = null;
    s.progress = 5;
    this.emit(s);
    return {
      upload_url: `https://uploads.mock.invalid/uploads/${uid}/${sid}/${s.uploadId}`,
      upload_id: s.uploadId,
      required_headers: {
        "Content-Type": format.canonical,
        "x-goog-content-length-range": `0,${MAX_AUDIO_BYTES}`,
      },
    };
  }

  /** The canonical Content-Type a signed URL is pinned to (for the PUT handler). */
  uploadContentType(sid: string, uploadId: string): string | undefined {
    const s = this.sessions.get(sid);
    return s && s.uploadId === uploadId ? (s.uploadType ?? undefined) : undefined;
  }

  completeAudio(uid: string, sid: string): S["CreateSessionResponse"] {
    const s = this.own(uid, sid);
    if (s.state !== "uploading") bad(409, "invalid_state", "No upload is in progress.");
    s.state = "validating";
    s.step = "validate";
    s.progress = 10;
    this.emit(s);
    return { session: { id: s.id, status: s.state } };
  }

  // ---- rating -------------------------------------------------------------

  putRating(uid: string, sid: string, body: S["RatingPut"]): S["RatingPutResponse"] {
    const s = this.own(uid, sid);
    if (s.state === "deleting") bad(409, "invalid_state", "Session is being deleted.");
    const card = body.card ?? {};
    validateCard(card, body.final === true);
    const seq = this.n + 1;
    this.n += 1;
    if (!body.final) {
      s.draft = { card, updated_at: this.now().toISOString(), seq };
      return { draft: true };
    }
    const noRating = body.no_rating === true;
    const stored: S["RatingCard"] = noRating
      ? { change_goal: card.change_goal, coded_span: card.coded_span ?? null }
      : card;
    const rating: Rating = {
      rating_id: this.id("rt"),
      no_rating: noRating,
      has_content: !noRating && cardHasContent(card),
      card: stored,
      seq,
    };
    s.finals.push(rating);
    s.flags.rating_submitted = true;
    s.flags.has_rating = rating.has_content;
    this.emit(s);
    this.maybeStartFirstRun(s);
    return { rating_id: rating.rating_id, draft: false };
  }

  getRating(uid: string, sid: string): S["RatingGet"] {
    const s = this.own(uid, sid);
    const final = s.finals.at(-1);
    const out: S["RatingGet"] = {};
    if (final) out.final = { rating_id: final.rating_id, no_rating: final.no_rating, card: final.card };
    if (s.draft && (!final || s.draft.seq > final.seq))
      out.draft = { card: s.draft.card, updated_at: s.draft.updated_at };
    return out;
  }

  // ---- speakers, transcript ----------------------------------------------

  getSpeakers(uid: string, sid: string): S["SpeakersResponse"] {
    const s = this.own(uid, sid);
    if (!s.flags.transcript_ready) bad(409, "invalid_state", "Transcript is not ready.");
    return { speakers: sampleLines(this.turns(s)), clinician_speaker: s.clinician_speaker };
  }

  confirmSpeaker(uid: string, sid: string, speaker: string): S["CreateSessionResponse"] {
    const s = this.own(uid, sid);
    if (!s.flags.transcript_ready || s.state === "running" || s.state === "deleting")
      bad(409, "invalid_state", "Speakers cannot be confirmed now.");
    if (!this.turns(s).some((t) => t.speaker === speaker)) invalidParam("clinician_speaker is not a speaker");
    s.clinician_speaker = speaker;
    s.flags.speaker_confirmed = true;
    this.emit(s);
    if (s.state === "awaiting_input") this.maybeStartFirstRun(s);
    return { session: { id: s.id, status: s.state } };
  }

  getTranscript(uid: string, sid: string): S["TranscriptView"] {
    const s = this.own(uid, sid);
    if (!s.flags.transcript_ready) bad(409, "invalid_state", "Transcript is not ready.");
    const turns = this.turns(s).map((t) => ({
      ...t,
      role:
        s.clinician_speaker === null
          ? null
          : t.speaker === s.clinician_speaker
            ? ("clinician" as const)
            : ("client" as const),
    }));
    return {
      turns,
      language: s.language === "auto" ? "en-US" : s.language,
      duration_ms: turns.at(-1)?.end_ms ?? 0,
      clinician_speaker: s.clinician_speaker,
    };
  }

  // ---- runs, reports, usage ----------------------------------------------

  /** Start the first run once transcript + speaker + final rating are in (SP04 R4). */
  private maybeStartFirstRun(s: SessionRec): void {
    const f = s.flags;
    if (s.state !== "awaiting_input" || s.first_run_id) return;
    if (!(f.transcript_ready && f.speaker_confirmed && f.rating_submitted)) return;
    if (s.holdFirstStart || this.runsToday(s.uid) >= this.dailyCap) {
      s.error = { code: "daily_cap_reached" };
      this.emit(s);
      return;
    }
    this.createRun(s, {});
  }

  private createRun(s: SessionRec, p: S["RunRequest"]): RunRec {
    const run: RunRec = {
      run_id: this.id("r"),
      status: "running",
      n_runs: p.n_runs ?? s.n_runs,
      preset: p.preset ?? s.preset,
      stt: { provider: "mock", model: "mock-stt", language: s.language === "auto" ? "en-US" : s.language },
      rating_id: s.finals.at(-1)?.rating_id ?? null,
      code_version: "mock",
      stage: "paudit",
      stageIdx: 0,
    };
    s.runs.push(run);
    s.first_run_id ??= run.run_id;
    s.holdFirstStart = false;
    s.error = null;
    s.state = "running";
    s.step = "paudit";
    s.progress = RUN_START_PROGRESS;
    const key = this.dayKey(s.uid);
    this.runsByDay.set(key, (this.runsByDay.get(key) ?? 0) + 1);
    this.emit(s);
    return run;
  }

  startRun(uid: string, sid: string, body: S["RunRequest"]): S["RunCreated"] {
    const s = this.own(uid, sid);
    const ok = s.state === "awaiting_input" || s.state === "report_ready" || s.state === "failed";
    if (!ok || !s.flags.transcript_ready || !s.flags.speaker_confirmed)
      bad(409, "invalid_state", "A run cannot start in this state.");
    if (body.n_runs !== undefined && (!Number.isInteger(body.n_runs) || body.n_runs < 1 || body.n_runs > 5))
      invalidParam("n_runs must be an integer from 1 to 5");
    if (body.preset !== undefined && !PRESETS.includes(body.preset)) invalidParam("preset is not allowed");
    s.holdFirstStart = false; // the user pressed Start
    if (this.runsToday(uid) >= this.dailyCap)
      bad(429, "daily_cap_reached", "Daily run limit reached.");
    return { run_id: this.createRun(s, body).run_id };
  }

  listRuns(uid: string, sid: string): S["Run"][] {
    return this.own(uid, sid).runs.map(publicRun);
  }

  getRun(uid: string, runId: string): S["Run"] {
    for (const s of this.sessions.values()) {
      const r = s.uid === uid ? s.runs.find((x) => x.run_id === runId) : undefined;
      if (r) return publicRun(r);
    }
    return notFound();
  }

  listReports(uid: string, sid: string): S["ReportVersion"][] {
    return this.own(uid, sid).reports.map(({ version, report_id, run_id, created_at }) => ({
      version,
      report_id,
      run_id,
      created_at,
    }));
  }

  getReport(uid: string, sid: string, version: number): Report {
    const r = this.own(uid, sid).reports.find((x) => x.version === version);
    return r ? structuredClone(r.report) : notFound();
  }

  getUsage(uid: string): S["Usage"] {
    const d = this.now();
    const reset = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1));
    return { runs_today: this.runsToday(uid), daily_cap: this.dailyCap, resets_at: reset.toISOString() };
  }

  // ---- the worker, one step at a time -------------------------------------

  /** Advance one worker step for a session. Returns false when nothing moved. */
  advance(sid: string): boolean {
    const s = this.sessions.get(sid);
    if (!s) return false;

    if (s.state === "validating") {
      const code = this.injected(s, VALIDATE_FAILS);
      if (code) this.fail(s, code, "validate");
      else {
        s.state = "transcribing";
        s.step = "transcribe";
        s.progress = 20;
        this.emit(s);
      }
      return true;
    }

    if (s.state === "transcribing") {
      const code = this.injected(s, TRANSCRIBE_FAILS);
      if (code) this.fail(s, code, "transcribe");
      else {
        s.flags.transcript_ready = true;
        s.state = "awaiting_input";
        s.step = null;
        s.progress = 40;
        this.emit(s);
        this.maybeStartFirstRun(s);
      }
      return true;
    }

    if (s.state === "running") {
      const run = s.runs.at(-1);
      if (!run) return false;
      const stage = STAGES[run.stageIdx];
      if (stage === "paudit" && this.titleIs(s, "fail-paudit")) {
        run.status = "failed";
        this.fail(s, "internal_error", "paudit");
        return true;
      }
      s.progress += STAGE_WEIGHT[stage];
      run.stageIdx += 1;
      if (run.stageIdx < STAGES.length) {
        run.stage = STAGES[run.stageIdx];
        s.step = run.stage;
      } else {
        run.status = "done";
        run.stage = null;
        this.finishRun(s, run);
      }
      this.emit(s);
      return true;
    }
    return false;
  }

  private finishRun(s: SessionRec, run: RunRec): void {
    const rating = s.finals.find((r) => r.rating_id === run.rating_id);
    const created_at = this.now().toISOString();
    const report = reportFor({
      edge: this.titleIs(s, "utf8-edge"),
      hasRating: rating?.has_content ?? false,
      reasonsFailed: this.titleIs(s, "fail-eaudit"),
      tipsFailed: this.titleIs(s, "fail-tips"),
      createdAt: created_at,
    });
    report.header.n_runs = run.n_runs;
    report.header.preset = run.preset;
    s.reports.push({
      version: s.reports.length + 1,
      report_id: this.id("rp"),
      run_id: run.run_id,
      created_at,
      report,
    });
    s.state = "report_ready";
    s.step = null;
  }

  /** Advance until the session stops on a human wait or a terminal state. */
  settle(sid: string): void {
    for (let i = 0; i < 50 && this.advance(sid); i++);
  }

  /** One step for every session that is moving on its own (browser auto-advance). */
  advanceAll(): void {
    for (const sid of [...this.sessions.keys()]) this.advance(sid);
  }
}

function publicRun({ stageIdx: _ignored, ...run }: RunRec): S["Run"] {
  void _ignored;
  return { ...run };
}

function cardHasContent(card: S["RatingCard"]): boolean {
  const g = Object.values(card.globals ?? {}).some(
    (x) => (x.score ?? null) !== null || !!x.reason?.trim() || !!x.example?.text?.trim(),
  );
  const c = Object.values(card.counts ?? {}).some(
    (x) => (x.count ?? null) !== null || !!x.note?.trim(),
  );
  return g || c || !!card.notes?.trim();
}

/** Hard limits (SP04 R2): UI only warns, the API rejects with `rating_invalid`. */
function validateCard(card: S["RatingCard"], final: boolean): void {
  const errors: string[] = [];
  const max = (path: string, v: unknown, n: number) => {
    if (typeof v === "string" && v.length > n) errors.push(`${path} exceeds ${n} characters`);
  };
  if (final && !(typeof card.change_goal === "string" && card.change_goal.trim()))
    errors.push("change_goal is required");
  max("change_goal", card.change_goal, 1000);
  max("notes", card.notes, 3000);
  for (const [id, g] of Object.entries(card.globals ?? {})) {
    if (g.score != null && (!Number.isInteger(g.score) || g.score < 1 || g.score > 5))
      errors.push(`globals.${id}.score must be between 1 and 5`);
    max(`globals.${id}.reason`, g.reason, 1000);
    max(`globals.${id}.example.text`, g.example?.text, 1000);
  }
  for (const [id, c] of Object.entries(card.counts ?? {})) {
    if (c.count != null && (!Number.isInteger(c.count) || c.count < 0))
      errors.push(`counts.${id}.count must be a whole number, zero or more`);
    max(`counts.${id}.note`, c.note, 1000);
  }
  if (errors.length)
    bad(
      422,
      "rating_invalid",
      "The rating card is invalid.",
      errors.map((message) => ({ code: "rating_invalid", message })),
    );
}
