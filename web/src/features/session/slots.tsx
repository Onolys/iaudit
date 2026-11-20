/**
 * Mount points: the rating card (R4, `features/rating`) and the speaker gate (R4, a later task
 * that renders nothing yet; replace the body, keep the `data-slot`). The uploader (R3) lives in
 * `features/upload`.
 */
import type { SessionStatusDoc } from "../../api/statusListener";
import { RatingCard } from "../rating/RatingCard";
export { UploadSlot } from "../upload/UploadSlot";

export interface SlotProps {
  sessionId: string;
  doc: SessionStatusDoc;
}

export function RatingCardSlot({ sessionId }: SlotProps) {
  return (
    <div data-slot="rating-card" data-session={sessionId}>
      <RatingCard sessionId={sessionId} />
    </div>
  );
}

export function SpeakerGateSlot({ sessionId }: SlotProps) {
  return <div data-slot="speaker-gate" data-session={sessionId} />;
}
