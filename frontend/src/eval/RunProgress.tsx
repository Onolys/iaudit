import type { EvalError, RunDetail } from "./evalTypes";
import { EvalErrorMessage, ServerBanner } from "./ServerBanner";

export interface RunProgressProps {
  error: EvalError | null; conflict: string | null; run: RunDetail | null;
  aborting: boolean; downloading: boolean; downloadError: string | EvalError | null; lostContact: boolean;
  abort: () => void; attachConflict: () => void;
}
/** Renders the run/download state owned by useRunLifecycle. */
export function RunProgress({ error, conflict, run, aborting, downloading, downloadError, lostContact, abort, attachConflict }: RunProgressProps) {
  return <>
    {error && <EvalErrorMessage error={error} />}
    {conflict && <div><p>Run {conflict} is already active</p><button type="button" onClick={attachConflict}>Attach to active run</button></div>}
    {lostContact && <ServerBanner lostContact />}
    {downloading && <p role="status">downloading…</p>}
    {downloadError && <div role="alert">{typeof downloadError === "string" ? <p>{downloadError}</p> : <EvalErrorMessage error={downloadError} />}</div>}
    {run && <div aria-label={`Run ${run.run_id}`}>
      <span className="eval-state">{run.state === "aborted_cost" ? "aborted: cost cap" : run.state}</span>
      <p>{run.progress.done}/{run.progress.total}</p>
      <progress aria-label="Run progress" value={run.progress.done} max={run.progress.total || 1} />
      <p>Failures: {run.progress.failures}</p>
      {run.progress.cost_usd != null && <p>Cost: ${run.progress.cost_usd.toFixed(2)}</p>}
      {run.error && <p className="eval-error">{run.error.message}</p>}
      {run.state === "running" && <button type="button" disabled={aborting} onClick={abort}>{aborting ? "Aborting…" : "Abort"}</button>}
    </div>}
  </>;
}
