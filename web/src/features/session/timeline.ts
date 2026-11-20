/**
 * Session timeline derived from `state` + flags (PRD R4, D14). There is no per-gate
 * state: speaker and rating are flags, and `awaiting_input` is the one wait state.
 */
import { messageForCode } from "../../api/errors";
import type { SessionStatusDoc } from "../../api/statusListener";

export type StepKey = "upload" | "validate" | "transcribe" | "speaker" | "rating" | "run" | "report";
export type StepStatus = "done" | "current" | "pending" | "failed";

export interface TimelineStep {
  key: StepKey;
  label: string;
  status: StepStatus;
  subLabel?: string;
}

export interface Timeline {
  steps: TimelineStep[];
  /** One or more plain lines for the `aria-live` status text. */
  lines: string[];
  /** Show "Usually under 5 minutes ..." (only once the run has started). */
  showRunCopy: boolean;
  /** `awaiting_input` stopped by the daily cap: offer Start. */
  capReached: boolean;
}

export type TimelineInput = Pick<
  SessionStatusDoc,
  "state" | "step" | "error_code" | "transcript_ready" | "speaker_confirmed" | "rating_submitted"
>;

const LABELS: Record<StepKey, string> = {
  upload: "Upload",
  validate: "Check audio",
  transcribe: "Transcribe",
  speaker: "Confirm speaker",
  rating: "Your rating",
  run: "Rate session",
  report: "Report",
};
const ORDER = Object.keys(LABELS) as StepKey[];
export const STEP_LABELS = ORDER.map((k) => LABELS[k]);

const RUN_SUBLABELS: Record<string, string> = {
  paudit: "Rating the session",
  eaudit: "Checking your reasons",
  tips: "Writing tips",
  compare: "Comparing",
  assemble: "Building the report",
};

const VALIDATE_CODES = new Set(["unsupported_audio", "audio_too_long", "audio_too_large", "audio_unreadable"]);
const TRANSCRIBE_CODES = new Set(["no_speech", "speakers_not_separated", "transcription_failed"]);

/** Which step a `failed` session stopped at, from the error code and what had finished. */
function failedAt(code: string | null, transcriptReady: boolean): StepKey {
  if (code && VALIDATE_CODES.has(code)) return "validate";
  if (code && TRANSCRIBE_CODES.has(code)) return "transcribe";
  return transcriptReady ? "run" : "transcribe";
}

export interface TimelineOptions {
  /** Reset time for the cap message, already formatted for display. */
  resetsAt?: string;
}

export function deriveTimeline(doc: TimelineInput, opts: TimelineOptions = {}): Timeline {
  const { state, transcript_ready: tr, speaker_confirmed: sp, rating_submitted: rt } = doc;
  const inputs = state === "awaiting_input";
  const afterTranscribe = inputs || state === "running" || state === "report_ready";
  const failedStep = state === "failed" ? failedAt(doc.error_code, tr) : null;
  const deleting = state === "deleting";

  const status: Record<StepKey, StepStatus> = {
    upload: "pending",
    validate: "pending",
    transcribe: "pending",
    speaker: "pending",
    rating: "pending",
    run: "pending",
    report: "pending",
  };

  if (!deleting) {
    // Upload / Check audio / Transcribe follow the pipeline state.
    status.upload = state === "created" || state === "uploading" ? "current" : "done";
    status.validate =
      state === "validating" ? "current" : state === "created" || state === "uploading" ? "pending" : "done";
    status.transcribe =
      state === "transcribing"
        ? "current"
        : state === "created" || state === "uploading" || state === "validating"
          ? "pending"
          : tr || afterTranscribe
            ? "done"
            : "pending";
    if (state === "failed") {
      // Everything before the failing step finished; the failing step failed; the rest stays pending.
      const idx = ORDER.indexOf(failedStep!);
      ORDER.slice(0, 3).forEach((k, i) => {
        status[k] = i < idx ? "done" : i === idx ? "failed" : "pending";
      });
      if (failedStep === "run") status.run = "failed";
    }

    // Gates come from the flags alone.
    status.speaker = sp || state === "report_ready" ? "done" : inputs ? "current" : "pending";
    status.rating = rt || state === "report_ready" ? "done" : inputs ? "current" : "pending";
    if (state === "running") status.run = "current";
    if (state === "report_ready") {
      status.run = "done";
      status.report = "done";
    }
  }

  const steps: TimelineStep[] = ORDER.map((key) => ({ key, label: LABELS[key], status: status[key] }));
  const runStep = steps.find((s) => s.key === "run")!;
  const runLabel = state === "running" ? (RUN_SUBLABELS[doc.step ?? ""] ?? RUN_SUBLABELS.paudit) : undefined;
  if (runLabel) runStep.subLabel = runLabel;

  let capReached = false;
  let lines: string[];
  switch (state) {
    case "created":
      lines = ["Getting ready to upload your recording."];
      break;
    case "uploading":
      lines = ["Uploading your recording."];
      break;
    case "validating":
      lines = ["Checking your audio."];
      break;
    case "transcribing":
      lines = ["Transcribing the recording."];
      break;
    case "awaiting_input": {
      if (doc.error_code === "daily_cap_reached") {
        capReached = true;
        lines = [messageForCode("daily_cap_reached", { resetsAt: opts.resetsAt })];
        break;
      }
      lines = [];
      if (!sp) lines.push("Confirm who the clinician is");
      if (!rt) lines.push("Waiting for your rating");
      if (lines.length === 0) lines.push("Starting the rating.");
      break;
    }
    case "running":
      lines = [runLabel!];
      break;
    case "report_ready":
      lines = ["Your report is ready."];
      break;
    case "failed":
      lines = ["This session couldn't be completed."];
      break;
    case "deleting":
      lines = ["Deleting this session."];
      break;
  }

  return { steps, lines, showRunCopy: state === "running", capReached };
}
