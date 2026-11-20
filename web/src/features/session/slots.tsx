/**
 * Mount points owned by later tasks: the rating card (R4) and the speaker gate (R4).
 * Each renders nothing yet; replace the body, keep the `data-slot`. The uploader (R3) lives in
 * `features/upload`.
 */
import type { SessionStatusDoc } from "../../api/statusListener";
export { UploadSlot } from "../upload/UploadSlot";

export interface SlotProps {
  sessionId: string;
  doc: SessionStatusDoc;
}

export function RatingCardSlot({ sessionId }: SlotProps) {
  return <div data-slot="rating-card" data-session={sessionId} />;
}

export function SpeakerGateSlot({ sessionId }: SlotProps) {
  return <div data-slot="speaker-gate" data-session={sessionId} />;
}
