import type { components } from "../../api/schema";

type State = components["schemas"]["SessionListItem"]["status"];

export interface StatusChip {
  text: string;
  tone: "progress" | "wait" | "done" | "failed";
}

/** Dashboard status chip (PRD R5): text says it, tone only adds colour. */
export const STATUS_CHIP: Record<State, StatusChip> = {
  created: { text: "Uploading", tone: "progress" },
  uploading: { text: "Uploading", tone: "progress" },
  validating: { text: "Checking audio", tone: "progress" },
  transcribing: { text: "Transcribing", tone: "progress" },
  awaiting_input: { text: "Needs your input", tone: "wait" },
  running: { text: "Rating", tone: "progress" },
  report_ready: { text: "Report ready", tone: "done" },
  failed: { text: "Failed", tone: "failed" },
  deleting: { text: "Deleting", tone: "progress" },
};
