import { useCallback, useEffect, useRef, useState } from "react";
import type { EvalApi } from "./evalApi";
import type { EvalError, MetricsReport, RunDetail as RunData, ScoreState } from "./evalTypes";
import { usePolling } from "./usePolling";
import { EvalErrorMessage, ServerBanner } from "./ServerBanner";
import { MetricsTable } from "./MetricsTable";
import { ItemList } from "./ItemList";
import { RunInfoBlock } from "./RunInfoBlock";

interface Props { api: EvalApi; runId: string; onOpenItem: (itemId: string) => void; onBack: () => void }
interface MetricsState { revision: number; data: MetricsReport | null; error: EvalError | null; loading: boolean }
const scoringActive = (state: ScoreState) => state === "pending" || state === "running";
function RequestError({ error, onRetry }: { error: EvalError; onRetry: () => void }) {
  return error.kind === "api" ? <div role="alert"><EvalErrorMessage error={error} /><button type="button" onClick={onRetry}>Retry</button></div>
    : <ServerBanner error={error} onRetry={onRetry} />;
}

/** Remount local generations when the selected run changes, cancelling every old request. */
export function RunDetail(props: Props) { return <RunContent key={props.runId} {...props} />; }

function RunContent({ api, runId, onOpenItem, onBack }: Props) {
  const [cycle, setCycle] = useState(0);
  const [lastRun, setLastRun] = useState<RunData | null>(null);
  const [metricsRevision, setMetricsRevision] = useState(0);
  const [metrics, setMetrics] = useState<MetricsState>({ revision: 0, data: null, error: null, loading: true });
  const [posting, setPosting] = useState(false);
  const [waitingForScore, setWaitingForScore] = useState(false);
  const [postError, setPostError] = useState<EvalError | null>(null);
  const previousScore = useRef<ScoreState | null>(null);
  const rescoreRequested = useRef(false);
  const postController = useRef<AbortController | null>(null);
  const postPending = useRef(false);
  const pollRun = useCallback(async (signal: AbortSignal) => {
    const result = await api.getRun(runId, { signal });
    return result.ok ? { ok: true as const, value: { run: result.value, cycle } } : result;
  }, [api, runId, cycle]);
  const poll = usePolling(pollRun, { enabled: true, isTerminal: value => !scoringActive(value.run.score_state) });
  const current = poll.data?.cycle === cycle ? poll.data : null;
  const run = current?.run ?? lastRun;
  useEffect(() => {
    if (!current) return;
    setLastRun(current.run);
    const score = current.run.score_state;
    if (!scoringActive(score)) {
      if (rescoreRequested.current || previousScore.current !== null && scoringActive(previousScore.current)) {
        setMetricsRevision(value => value + 1);
      }
      rescoreRequested.current = false; setWaitingForScore(false);
    }
    previousScore.current = score;
  }, [current]);

  useEffect(() => {
    const controller = new AbortController();
    setMetrics({ revision: metricsRevision, data: null, error: null, loading: true });
    void api.getMetrics(runId, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      setMetrics(result.ok
        ? { revision: metricsRevision, data: result.value, error: null, loading: false }
        : { revision: metricsRevision, data: null, error: result.error, loading: false });
    });
    return () => controller.abort();
  }, [api, runId, metricsRevision]);
  useEffect(() => () => postController.current?.abort(), []);
  const retry = () => { setPostError(null); setCycle(value => value + 1); setMetricsRevision(value => value + 1); };
  async function rescore() {
    if (!run || run.state === "running" || scoringActive(run.score_state) || waitingForScore || postPending.current) return;
    postPending.current = true;
    const controller = new AbortController(); postController.current = controller;
    setPosting(true); setPostError(null);
    const result = await api.rescore(runId, { signal: controller.signal });
    if (controller.signal.aborted) return;
    postPending.current = false; setPosting(false);
    if (!result.ok) { setPostError(result.error); return; }
    rescoreRequested.current = true; setWaitingForScore(true); setCycle(value => value + 1);
  }
  const scoring = posting || waitingForScore || !!run && scoringActive(run.score_state);
  const report = metrics.revision === metricsRevision ? metrics.data : null;
  const metricsLoading = metrics.revision !== metricsRevision || metrics.loading;
  const metricError = metrics.revision === metricsRevision ? metrics.error : null;
  const loadError = !run && poll.error ? poll.error : metricError;
  return <section className="eval-panel" aria-label="Run detail">
    <button type="button" onClick={onBack}>Back to runs</button>
    {run ? <>
      <h2>{run.dataset} · {run.split} · N={run.n_items}</h2>
      <p>{run.created_at}</p>
      <span className="chip">{run.state === "aborted_cost" ? "aborted: cost cap" : run.state}</span>{" "}
    </> : <p role="status">Loading run…</p>}
    <button type="button" disabled={!run || run.state === "running" || scoring} onClick={() => void rescore()}>Re-score</button>
    {poll.stale ? <ServerBanner lostContact /> : loadError && <RequestError error={loadError} onRetry={retry} />}
    {postError && <RequestError error={postError} onRetry={() => { setPostError(null); void rescore(); }} />}
    {run && <>
      {run.error && <p className="eval-error">{run.error.message}</p>}
      {(scoring || run.score_state !== "done" || !report) && <p>Failures: {run.totals.failures} of {run.n_items}. Primary counts them wrong; secondary excludes them.</p>}
      {scoring ? <p role="status">Scoring...</p> : run.score_state === "failed" ? <p>Scoring failed. Re-score to retry.</p>
        : metricsLoading ? <p role="status">Loading metrics…</p> : report ? <MetricsTable report={report} />
        : !metricError && <p>Metrics missing. Re-score.</p>}
      <ItemList api={api} runId={runId} onOpenItem={onOpenItem} refreshKey={metricsRevision} />
      <RunInfoBlock run={run} />
    </>}
  </section>;
}
