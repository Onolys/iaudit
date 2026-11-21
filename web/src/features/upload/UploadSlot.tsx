/** Upload progress, cancel and "Retry upload" on the session page (PRD R3). */
import { useSyncExternalStore } from "react";
import type { SessionStatusDoc } from "../../api/statusListener";
import { getJob, subscribeRegistry, type UploadJob } from "./uploader";

const NO_STATE = { phase: "idle", loaded: 0, total: 0, attempt: 0 } as const;
const mb = (n: number) => (n / (1024 * 1024)).toFixed(1);

function useJob(sessionId: string): UploadJob | undefined {
  return useSyncExternalStore(subscribeRegistry, () => getJob(sessionId));
}

export function UploadSlot({ sessionId }: { sessionId: string; doc: SessionStatusDoc }) {
  const job = useJob(sessionId);
  const state = useSyncExternalStore(
    (fn) => (job ? job.subscribe(fn) : () => undefined),
    () => (job ? job.getState() : NO_STATE),
  );

  if (!job) {
    return (
      <div data-slot="upload" data-session={sessionId}>
        <p className="notice">
          This upload isn't running in this tab. Start a new session to upload the file again.
        </p>
      </div>
    );
  }

  const pct = state.total > 0 ? Math.min(100, Math.round((state.loaded / state.total) * 100)) : 0;
  return (
    <div data-slot="upload" data-session={sessionId}>
      {state.phase === "uploading" || state.phase === "completing" ? (
        <>
          <p>
            <progress max={100} value={pct} aria-label="Upload progress" /> {mb(state.loaded)} of{" "}
            {mb(state.total)} MB ({pct}%)
          </p>
          {state.attempt > 0 ? <p className="form-note">Trying again…</p> : null}
          {state.phase === "uploading" ? (
            <button type="button" className="btn btn-secondary" onClick={() => job.cancel()}>
              Cancel upload
            </button>
          ) : null}
        </>
      ) : null}
      {state.phase === "done" ? <p className="form-note">Upload finished.</p> : null}
      {state.phase === "failed" || state.phase === "cancelled" ? (
        <>
          <p className="form-error" role="alert">
            {state.phase === "cancelled" ? "Upload cancelled." : "The upload didn't finish."}
          </p>
          <button type="button" className="btn btn-primary" onClick={() => void job.retry()}>
            Retry upload
          </button>
        </>
      ) : null}
    </div>
  );
}
