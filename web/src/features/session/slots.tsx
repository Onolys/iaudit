/**
 * Mount points owned by later tasks: the uploader (R3), the rating card (R4) and the
 * speaker gate (R4). Each renders nothing yet; replace the body, keep the `data-slot`.
 */
import type { SessionStatusDoc } from "../../api/statusListener";

export interface SlotProps {
  sessionId: string;
  doc: SessionStatusDoc;
}

export function UploadSlot({ sessionId }: SlotProps) {
  return <div data-slot="upload" data-session={sessionId} />;
}

export function RatingCardSlot({ sessionId }: SlotProps) {
  return <div data-slot="rating-card" data-session={sessionId} />;
}

export function SpeakerGateSlot({ sessionId }: SlotProps) {
  return <div data-slot="speaker-gate" data-session={sessionId} />;
}
