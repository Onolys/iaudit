import { describe, expect, it } from "vitest";
import {
  ApiError,
  ERROR_CODES,
  GENERIC_MESSAGE,
  describeError,
  failureAction,
  messageForCode,
  parseErrorBody,
} from "./errors";

const body = (status: number, code: string, extra: object = {}) => ({
  schema_version: "0.0.1",
  status,
  message: "fixed text",
  details: [{ code, message: "fixed text" }],
  request_id: "req_123",
  ...extra,
});

describe("messageForCode", () => {
  it.each(ERROR_CODES)("has a plain, non-empty message for %s", (code) => {
    const msg = messageForCode(code);
    expect(msg.length).toBeGreaterThan(10);
    // plain text: no code names, no HTTP jargon
    expect(msg).not.toContain(code);
    expect(msg).not.toMatch(/\b(4\d\d|5\d\d)\b/);
  });

  it("uses the exact copy the PRD names for the transcription codes", () => {
    expect(messageForCode("no_speech")).toBe("We couldn't hear enough speech in this recording");
    expect(messageForCode("speakers_not_separated")).toBe(
      "We couldn't tell the two speakers apart in this recording",
    );
    expect(messageForCode("transcription_failed")).toBe("Transcription didn't finish");
  });

  it("mentions the reset time for daily_cap_reached when known", () => {
    expect(messageForCode("daily_cap_reached", { resetsAt: "tomorrow 00:00" })).toContain(
      "tomorrow 00:00",
    );
    expect(messageForCode("daily_cap_reached")).toContain("today's limit");
  });

  it("falls back to the generic message for unknown codes", () => {
    expect(messageForCode("something_new")).toBe(GENERIC_MESSAGE);
    expect(messageForCode(undefined)).toBe(GENERIC_MESSAGE);
  });
});

describe("parseErrorBody", () => {
  it.each(ERROR_CODES)("parses a public-error-response with code %s", (code) => {
    const err = parseErrorBody(422, body(422, code));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe(code);
    expect(err.status).toBe(422);
    expect(err.requestId).toBe("req_123");
    expect(err.userMessage).toBe(messageForCode(code));
  });

  it("keeps per-field details (rating_invalid)", () => {
    const err = parseErrorBody(422, {
      ...body(422, "rating_invalid"),
      details: [
        { code: "rating_invalid", message: "globals.cct.reason exceeds 1000 characters" },
        { code: "rating_invalid", message: "notes exceeds 3000 characters" },
      ],
    });
    expect(err.details.map((d) => d.message)).toEqual([
      "globals.cct.reason exceeds 1000 characters",
      "notes exceeds 3000 characters",
    ]);
  });

  it("degrades to a generic error for a non-contract body", () => {
    const err = parseErrorBody(502, "<html>bad gateway</html>");
    expect(err.code).toBe("unknown");
    expect(err.userMessage).toBe(GENERIC_MESSAGE);
    expect(err.status).toBe(502);
  });

  it("maps a bare 429 without a code to rate_limited", () => {
    expect(parseErrorBody(429, {}).code).toBe("rate_limited");
  });
});

describe("describeError", () => {
  it("describes an ApiError with its reference", () => {
    const d = describeError(parseErrorBody(409, body(409, "invalid_state")));
    expect(d).toEqual({
      code: "invalid_state",
      message: messageForCode("invalid_state"),
      requestId: "req_123",
    });
  });

  it("describes any other thrown value generically", () => {
    expect(describeError(new TypeError("Failed to fetch"))).toEqual({
      code: "unknown",
      message: GENERIC_MESSAGE,
      requestId: undefined,
    });
  });
});

describe("failureAction", () => {
  it.each([
    "unsupported_audio",
    "audio_too_long",
    "audio_too_large",
    "audio_unreadable",
    "no_speech",
    "speakers_not_separated",
    "transcription_failed",
  ])("%s offers a new upload", (code) => {
    expect(failureAction(code)).toBe("upload_new");
  });

  it.each(["upstream_unavailable", "internal_error", "unknown", undefined])(
    "%s offers Run again",
    (code) => {
      expect(failureAction(code)).toBe("run_again");
    },
  );
});
