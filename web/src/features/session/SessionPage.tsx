/**
 * `/sessions/:id` (PRD R4, D7, D14): status timeline derived from the live status doc,
 * gate slots, error cards and delete. The upload, rating card and speaker gate mount in
 * `slots.tsx`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { unwrap } from "../../api/client";
import { describeError, failureAction, messageForCode } from "../../api/errors";
import type { SessionStatusDoc } from "../../api/statusListener";
import { useApiClient } from "../../auth/useApiClient";
import { formatElapsed, formatResetTime } from "../../lib/format";
import { DeleteDialog } from "./DeleteDialog";
import { ErrorCard } from "./ErrorCard";
import { RatingCardSlot, SpeakerGateSlot, UploadSlot } from "./slots";
import { deriveTimeline } from "./timeline";
import { useSessionStatus } from "./useSessionStatus";

export function SessionPage() {
  const { id = "" } = useParams();
  return <SessionView key={id} id={id} />;
}

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

function SessionView({ id }: { id: string }) {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const deleting = useRef(false);
  const view = useSessionStatus(id, deleting);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const deleteButton = useRef<HTMLButtonElement>(null);

  const doc: SessionStatusDoc | null = view.phase === "live" || view.phase === "fallback" ? view.doc : null;
  const runStartedAt = view.phase === "live" ? view.runStartedAt : null;
  const now = useNow(runStartedAt !== null);

  const needsUsage = doc !== null && (doc.state === "failed" || doc.error_code === "daily_cap_reached");
  const usage = useQuery({
    queryKey: ["usage"],
    enabled: needsUsage,
    queryFn: async () => unwrap(await client.GET("/usage")),
  });
  const atCap = usage.data ? usage.data.runs_today >= usage.data.daily_cap : false;
  const resetsAt = formatResetTime(usage.data?.resets_at);

  const run = useMutation({
    mutationFn: async () => unwrap(await client.POST("/sessions/{id}/runs", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["usage"] }),
  });

  const remove = useMutation({
    mutationFn: async () => {
      deleting.current = true; // the doc vanishing is expected, not an error
      try {
        unwrap(await client.DELETE("/sessions/{id}", { params: { path: { id } } }));
      } catch (e) {
        deleting.current = false;
        throw e;
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      void navigate("/");
    },
  });

  const closeDialog = () => {
    setConfirmDelete(false);
    remove.reset();
    deleteButton.current?.focus();
  };

  if (view.phase === "error") {
    return (
      <>
        <h1>Session</h1>
        <ErrorCard code={view.error.code} reference={view.error.requestId}>
          <Link to="/">Back to your sessions</Link>
        </ErrorCard>
      </>
    );
  }

  const timeline = doc ? deriveTimeline(doc, { resetsAt }) : null;
  const failureCode = doc?.state === "failed" ? (doc.error_code ?? undefined) : undefined;
  const runError = run.error ? describeError(run.error, { resetsAt }) : null;
  const runLocked = run.isPending || atCap;

  return (
    <>
      <h1>Session</h1>

      <div className="timeline-status" role="status" aria-live="polite">
        {timeline ? timeline.lines.map((l) => <p key={l}>{l}</p>) : <p>Loading session…</p>}
      </div>

      {!doc || !timeline ? null : (
        <>
          {view.phase === "fallback" ? (
            <p className="notice" role="alert">
              Live updates stopped. This is the latest we could load.{" "}
              <button type="button" className="link-button" onClick={() => window.location.reload()}>
                Refresh
              </button>
            </p>
          ) : null}

          <ol className="timeline" aria-label="Progress">
            {timeline.steps.map((s) => (
              <li key={s.key} className={`timeline-step timeline-${s.status}`}>
                <span className="timeline-label">{s.label}</span>{" "}
                <span className="timeline-state">
                  ({s.status === "done" ? "done" : s.status === "current" ? "in progress" : s.status === "failed" ? "failed" : "not started"})
                </span>
                {s.subLabel ? <span className="timeline-sub"> {s.subLabel}</span> : null}
              </li>
            ))}
          </ol>

          {timeline.showRunCopy ? (
            <>
              <p className="form-note">
                Usually under 5 minutes — you can close this tab and come back; your report will be here.
              </p>
              {runStartedAt !== null ? <p className="form-note">Elapsed {formatElapsed(now - runStartedAt)}</p> : null}
              {doc.progress > 0 ? (
                <p className="form-note">
                  <progress max={100} value={doc.progress} aria-label="Progress" /> {doc.progress}%
                </p>
              ) : null}
            </>
          ) : null}

          {timeline.capReached ? (
            <p>
              <button type="button" className="btn btn-primary" disabled={runLocked} onClick={() => run.mutate()}>
                Start
              </button>
            </p>
          ) : null}

          {doc.state === "report_ready" && doc.latest_report_version !== null ? (
            <p>
              <Link className="btn btn-primary" to={`/sessions/${id}/reports/${doc.latest_report_version}`}>
                View report
              </Link>
            </p>
          ) : null}

          {doc.state === "failed" ? (
            <ErrorCard code={failureCode} reference={id} resetsAt={resetsAt}>
              {failureAction(failureCode) === "upload_new" ? (
                <Link className="btn btn-primary" to={`/sessions/new?from=${encodeURIComponent(id)}`}>
                  Upload a different file
                </Link>
              ) : (
                <>
                  <button type="button" className="btn btn-primary" disabled={runLocked} onClick={() => run.mutate()}>
                    Run again
                  </button>
                  {atCap ? <span>{messageForCode("daily_cap_reached", { resetsAt })}</span> : null}
                </>
              )}
            </ErrorCard>
          ) : null}

          {runError ? <ErrorCard code={runError.code} reference={runError.requestId} resetsAt={resetsAt} /> : null}

          {doc.state === "created" || doc.state === "uploading" ? <UploadSlot sessionId={id} doc={doc} /> : null}
          {doc.state !== "deleting" ? <RatingCardSlot sessionId={id} doc={doc} /> : null}
          {doc.transcript_ready && !doc.speaker_confirmed && doc.state !== "deleting" ? (
            <SpeakerGateSlot sessionId={id} doc={doc} />
          ) : null}

          <p>
            <button
              ref={deleteButton}
              type="button"
              className="btn btn-secondary"
              onClick={() => setConfirmDelete(true)}
            >
              Delete session
            </button>
          </p>
        </>
      )}

      {confirmDelete ? (
        <DeleteDialog busy={remove.isPending} onConfirm={() => remove.mutate()} onCancel={closeDialog}>
          {remove.error ? (
            <ErrorCard
              code={describeError(remove.error).code}
              reference={describeError(remove.error).requestId}
            />
          ) : null}
        </DeleteDialog>
      ) : null}
    </>
  );
}
