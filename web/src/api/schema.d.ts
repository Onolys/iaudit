/**
 * HAND-WRITTEN stand-in for the `openapi-typescript` output of `api/openapi.json`
 * (SP04 T1 creates the real file; SP05 T13 replaces this file with generated
 * types and `gen:api`). Shapes come from the SP04 PRD (R2, R4, R7, R9) and are
 * the single place to fix when the generated contract differs.
 */

export type SessionState =
  | "created"
  | "uploading"
  | "validating"
  | "transcribing"
  | "awaiting_input"
  | "running"
  | "report_ready"
  | "failed"
  | "deleting";

export type RunStage = "paudit" | "eaudit" | "tips" | "compare" | "assemble";

type Json<T> = { content: { "application/json": T } };
type Res<T> = { headers: { [name: string]: unknown }; content: { "application/json": T } };
type NoContent = { headers: { [name: string]: unknown }; content?: never };
type Params<P = never, Q = never, H = never> = ([P] extends [never]
  ? { path?: never }
  : { path: P }) &
  ([Q] extends [never] ? { query?: never } : { query?: Q }) &
  ([H] extends [never] ? { header?: never } : { header?: H }) & { cookie?: never };
type NoParams = { path?: never; query?: never; header?: never; cookie?: never };

export interface components {
  schemas: {
    ErrorDetail: { code: string; message: string };
    /** `public-error-response.schema.json`, schema_version "0.0.1". */
    ErrorResponse: {
      schema_version: string;
      request_id?: string;
      status: number;
      message: string;
      details: components["schemas"]["ErrorDetail"][];
    };
    SessionFlags: {
      transcript_ready: boolean;
      speaker_confirmed: boolean;
      rating_submitted: boolean;
      has_rating: boolean;
    };
    SessionRef: { id: string; status: SessionState };
    CreateSessionRequest: {
      language?: string;
      n_runs?: number;
      preset?: string;
      title?: string;
    };
    CreateSessionResponse: { session: components["schemas"]["SessionRef"] };
    SessionListItem: {
      id: string;
      title: string | null;
      status: SessionState;
      created_at: string;
      latest_report_version: number | null;
      error_code: string | null;
    };
    SessionList: { items: components["schemas"]["SessionListItem"][]; next_cursor?: string };
    SessionDetail: {
      id: string;
      title: string | null;
      status: SessionState;
      step: string | null;
      progress: number;
      flags: components["schemas"]["SessionFlags"];
      warnings: string[];
      error?: { code: string; step?: string } | null;
      latest_report_version: number | null;
    };
    AudioUploadRequest: { content_type: string; size_bytes: number; filename_ext: string };
    AudioUploadResponse: {
      upload_url: string;
      upload_id: string;
      required_headers: { [name: string]: string };
    };
    RatingCard: {
      change_goal?: string | null;
      coded_span?: { from_s: number | null; to_s: number | null } | null;
      globals?: {
        [item_id: string]: {
          score?: number | null;
          reason?: string;
          example?: { at_s: number | null; text: string } | null;
        };
      };
      counts?: { [item_id: string]: { count?: number | null; note?: string } };
      notes?: string;
    };
    RatingPut: { final: boolean; no_rating?: boolean; card: components["schemas"]["RatingCard"] };
    RatingPutResponse: { rating_id?: string; draft: boolean };
    RatingGet: {
      final?: { rating_id: string; no_rating: boolean; card: components["schemas"]["RatingCard"] };
      draft?: { card: components["schemas"]["RatingCard"]; updated_at: string };
    };
    SpeakerSample: { speaker: string; turn_count: number; samples: string[] };
    SpeakersResponse: {
      speakers: components["schemas"]["SpeakerSample"][];
      clinician_speaker: string | null;
    };
    SpeakerConfirmRequest: { clinician_speaker: string };
    TranscriptTurn: {
      id: string;
      speaker?: string | null;
      /** `clinician`/`client`; null until the clinician is confirmed. */
      role?: string | null;
      start_ms?: number | null;
      end_ms?: number | null;
      text: string;
    };
    TranscriptView: {
      turns: components["schemas"]["TranscriptTurn"][];
      language?: string | null;
      duration_ms?: number | null;
      clinician_speaker?: string | null;
    };
    RunRequest: { n_runs?: number; preset?: string };
    RunCreated: { run_id: string };
    Run: {
      run_id: string;
      status: "pending" | "running" | "done" | "failed";
      n_runs: number;
      preset: string;
      stt: { provider: string; model: string; language: string };
      rating_id: string | null;
      code_version: string;
      stage: RunStage | null;
    };
    ReportVersion: { version: number; report_id: string; run_id: string; created_at: string };
    Usage: { runs_today: number; daily_cap: number; resets_at: string };
  };
}

type S = components["schemas"];

export interface paths {
  "/sessions": {
    get: {
      parameters: Params<never, { limit?: number; cursor?: string }>;
      responses: { 200: Res<S["SessionList"]>; default: Res<S["ErrorResponse"]> };
    };
    post: {
      parameters: Params<never, never, { "Idempotency-Key"?: string }>;
      requestBody: Json<S["CreateSessionRequest"]>;
      responses: { 201: Res<S["CreateSessionResponse"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}": {
    get: {
      parameters: Params<{ id: string }>;
      responses: { 200: Res<S["SessionDetail"]>; default: Res<S["ErrorResponse"]> };
    };
    delete: {
      parameters: Params<{ id: string }>;
      responses: { 204: NoContent; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/audio": {
    post: {
      parameters: Params<{ id: string }>;
      requestBody: Json<S["AudioUploadRequest"]>;
      responses: { 200: Res<S["AudioUploadResponse"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/audio/complete": {
    post: {
      parameters: Params<{ id: string }>;
      responses: { 202: Res<S["CreateSessionResponse"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/rating": {
    get: {
      parameters: Params<{ id: string }>;
      responses: { 200: Res<S["RatingGet"]>; default: Res<S["ErrorResponse"]> };
    };
    put: {
      parameters: Params<{ id: string }>;
      requestBody: Json<S["RatingPut"]>;
      responses: { 202: Res<S["RatingPutResponse"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/speakers": {
    get: {
      parameters: Params<{ id: string }>;
      responses: { 200: Res<S["SpeakersResponse"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/speakers/confirm": {
    post: {
      parameters: Params<{ id: string }>;
      requestBody: Json<S["SpeakerConfirmRequest"]>;
      responses: { 202: Res<S["CreateSessionResponse"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/transcript": {
    get: {
      parameters: Params<{ id: string }>;
      responses: { 200: Res<S["TranscriptView"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/runs": {
    get: {
      parameters: Params<{ id: string }>;
      responses: { 200: Res<S["Run"][]>; default: Res<S["ErrorResponse"]> };
    };
    post: {
      parameters: Params<{ id: string }>;
      requestBody?: Json<S["RunRequest"]>;
      responses: { 202: Res<S["RunCreated"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/runs/{run_id}": {
    get: {
      parameters: Params<{ run_id: string }>;
      responses: { 200: Res<S["Run"]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/reports": {
    get: {
      parameters: Params<{ id: string }>;
      responses: { 200: Res<S["ReportVersion"][]>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/sessions/{id}/reports/{version}": {
    get: {
      parameters: Params<{ id: string; version: number }>;
      responses: { 200: Res<import("./report").Report>; default: Res<S["ErrorResponse"]> };
    };
  };
  "/usage": {
    get: {
      parameters: NoParams;
      responses: { 200: Res<S["Usage"]>; default: Res<S["ErrorResponse"]> };
    };
  };
}
