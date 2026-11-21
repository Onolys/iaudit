/**
 * Speaker gate (PRD R4, AC6b): the one machine guess a person confirms. One card per speaker with
 * up to three sample lines (rendered as text, never HTML). Everyone who is not the clinician counts
 * as the client. After a run (`report_ready` / `failed`) the same cards reopen with "Save and run
 * again": confirming then only changes the clinician for the next run, so a new run is started.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { unwrap } from "../../api/client";
import { describeError } from "../../api/errors";
import { useApiClient } from "../../auth/useApiClient";
import { ErrorCard } from "../session/ErrorCard";

export interface SpeakerGateProps {
  sessionId: string;
  /** `first`: pick and go. `rerun`: preselect the current clinician; save, then start a new run. */
  mode: "first" | "rerun";
  onDone?: () => void;
}

export function SpeakerGate({ sessionId, mode, onDone }: SpeakerGateProps) {
  const client = useApiClient();
  const speakers = useQuery({
    queryKey: ["speakers", sessionId],
    staleTime: 0,
    gcTime: 0,
    queryFn: async () => unwrap(await client.GET("/sessions/{id}/speakers", { params: { path: { id: sessionId } } })),
  });
  const [chosen, setChosen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (speakers.isPending) return <p className="form-note">Loading speakers…</p>;
  if (speakers.isError) {
    return (
      <p className="notice">
        We couldn't load the speakers.{" "}
        <button type="button" className="link-button" onClick={() => void speakers.refetch()}>
          Try again
        </button>
      </p>
    );
  }

  const { speakers: list, clinician_speaker: current } = speakers.data;
  const selected = chosen ?? current ?? null;

  async function confirm(speaker: string, thenRun: boolean) {
    setBusy(true);
    setError(null);
    try {
      unwrap(
        await client.POST("/sessions/{id}/speakers/confirm", {
          params: { path: { id: sessionId } },
          body: { clinician_speaker: speaker },
        }),
      );
      if (thenRun) unwrap(await client.POST("/sessions/{id}/runs", { params: { path: { id: sessionId } } }));
      onDone?.();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const err = error ? describeError(error) : null;
  return (
    <section className="speaker-gate" aria-labelledby="speaker-gate-heading">
      <h2 id="speaker-gate-heading">Who is the clinician?</h2>
      <p className="form-note">
        We separated the voices automatically. Check the lines below and tell us which speaker is the clinician.
        {list.length > 2 ? " Everyone else is the client." : ""}
      </p>
      <ul className="speaker-cards" aria-label="Speakers">
        {list.map((s) => (
          <li key={s.speaker} className="speaker-card">
            <h3>Speaker {s.speaker}</h3>
            <ul className="speaker-samples" aria-label={`Sample lines from speaker ${s.speaker}`}>
              {s.samples.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
            {mode === "first" ? (
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void confirm(s.speaker, false)}>
                This is the clinician
              </button>
            ) : (
              <label>
                <input
                  type="radio"
                  name="clinician-speaker"
                  checked={selected === s.speaker}
                  disabled={busy}
                  onChange={() => setChosen(s.speaker)}
                />{" "}
                This is the clinician
              </label>
            )}
          </li>
        ))}
      </ul>
      {err ? <ErrorCard code={err.code} reference={err.requestId} /> : null}
      {mode === "rerun" ? (
        <p>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || selected === null}
            onClick={() => selected !== null && void confirm(selected, true)}
          >
            Save and run again
          </button>{" "}
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={onDone}>
            Cancel
          </button>
        </p>
      ) : null}
    </section>
  );
}
