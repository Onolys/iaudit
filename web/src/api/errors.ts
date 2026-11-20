/**
 * Error codes (SP04 R9 `public-error-response`, plus the R4 table of the web
 * PRD) mapped to plain, fixed messages. Messages never include server text or
 * instance values (R8: no PHI in error messages).
 */
import type { components } from "./schema";

export const GENERIC_MESSAGE = "Something went wrong. Please try again.";

const MESSAGES = {
  unsupported_audio:
    "We can't use this file type. Upload an mp3, wav, m4a, webm or ogg recording.",
  audio_too_long: "This recording is longer than 20 minutes. Upload a shorter one.",
  audio_too_large:
    "This file is over 300 MB. Export it as m4a or mp3 and upload that instead.",
  audio_unreadable: "We couldn't read this audio file. Try exporting it again as m4a or mp3.",
  no_speech: "We couldn't hear enough speech in this recording",
  speakers_not_separated: "We couldn't tell the two speakers apart in this recording",
  transcription_failed: "Transcription didn't finish",
  rating_invalid: "Some of your rating needs a change. Check the highlighted fields.",
  upstream_unavailable: "A service we depend on is busy right now. Please try again in a minute.",
  daily_cap_reached: "You've reached today's limit.",
  invalid_state: "That isn't possible at this stage of the session. Refresh and try again.",
  rate_limited: "You're going a little fast. Wait a moment and try again.",
  unauthenticated: "Your sign-in has expired. Please sign in again.",
  forbidden: "You don't have access to do that.",
  not_found: "We couldn't find that. It may have been deleted.",
  conflict: "That request clashes with an earlier one. Refresh and try again.",
  internal_error: GENERIC_MESSAGE,
} as const satisfies Record<string, string>;

export type ErrorCode = keyof typeof MESSAGES;
export const ERROR_CODES = Object.keys(MESSAGES) as ErrorCode[];

function isKnown(code: string | undefined): code is ErrorCode {
  return code !== undefined && Object.hasOwn(MESSAGES, code);
}

export interface MessageContext {
  /** Reset time for `daily_cap_reached`, already formatted for display. */
  resetsAt?: string;
}

export function messageForCode(code: string | undefined, ctx: MessageContext = {}): string {
  if (!isKnown(code)) return GENERIC_MESSAGE;
  if (code === "daily_cap_reached" && ctx.resetsAt) {
    return `You've reached today's limit. You can start the rating after ${ctx.resetsAt}.`;
  }
  return MESSAGES[code];
}

/** Which recovery the error card offers (R4 Failure). */
export type FailureAction = "upload_new" | "run_again";

const UPLOAD_NEW = new Set<string>([
  "unsupported_audio",
  "audio_too_long",
  "audio_too_large",
  "audio_unreadable",
  "no_speech",
  "speakers_not_separated",
  "transcription_failed",
]);

export function failureAction(code: string | undefined): FailureAction {
  return code !== undefined && UPLOAD_NEW.has(code) ? "upload_new" : "run_again";
}

type ErrorDetail = components["schemas"]["ErrorDetailModel"];

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ErrorDetail[];
  readonly requestId?: string;

  constructor(status: number, code: string, details: ErrorDetail[], requestId?: string) {
    super(`API error ${status} ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  get userMessage(): string {
    return messageForCode(this.code);
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

/** Turn a response body (expected: `public-error-response`) into an ApiError. */
export function parseErrorBody(status: number, body: unknown): ApiError {
  let details: ErrorDetail[] = [];
  let requestId: string | undefined;
  if (isRecord(body)) {
    if (Array.isArray(body.details)) {
      details = body.details.filter(
        (d): d is ErrorDetail =>
          isRecord(d) && typeof d.code === "string" && typeof d.message === "string",
      );
    }
    if (typeof body.request_id === "string") requestId = body.request_id;
  }
  let code: string | undefined = details[0]?.code;
  if (code === undefined) code = status === 429 ? "rate_limited" : "unknown";
  return new ApiError(status, code, details, requestId);
}

export interface ErrorDescription {
  code: string;
  message: string;
  requestId?: string;
}

export function describeError(err: unknown, ctx: MessageContext = {}): ErrorDescription {
  if (err instanceof ApiError) {
    return {
      code: err.code,
      message: messageForCode(err.code, ctx),
      requestId: err.requestId,
    };
  }
  return { code: "unknown", message: GENERIC_MESSAGE, requestId: undefined };
}
