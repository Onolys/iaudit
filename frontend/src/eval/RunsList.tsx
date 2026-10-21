import { useEffect, useRef, useState } from "react";
import type { EvalApi } from "./evalApi";
import type { EvalError, RunDetail, RunSummary } from "./evalTypes";
import { EvalErrorMessage } from "./ServerBanner";

interface Props {
  api: EvalApi;
  refreshKey?: number;
  activeRun?: RunDetail | null;
  runActive?: boolean;
  onResume: (run: RunSummary) => void;
  onResumePendingChange?: (pending: boolean) => void;
  onOpenRun: (runId: string) => void;
  onCompare: (a: string, b: string) => void;
}
const resumable = (run: RunSummary) => ["aborted", "aborted_cost", "interrupted", "failed"].includes(run.state)
  || run.state === "finished" && run.totals.failures > 0;

export function RunsList({ api, refreshKey = 0, activeRun, runActive = false, onResume, onResumePendingChange, onOpenRun, onCompare }: Props) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<EvalError | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [resuming, setResuming] = useState<string | null>(null);
  const listController = useRef<AbortController | null>(null);
  const resumeController = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const resumePending = useRef(false);
  const pendingCallback = useRef(onResumePendingChange);
  pendingCallback.current = onResumePendingChange;

  useEffect(() => {
    const controller = new AbortController(); listController.current = controller;
    const attempt = ++generation.current;
    void api.listRuns({ signal: controller.signal }).then(result => {
      if (controller.signal.aborted || attempt !== generation.current) return;
      if (!result.ok) { setError(result.error); return; }
      setError(null); setRuns(result.value);
      setSelected(previous => previous.filter(id => result.value.some(run => run.run_id === id)));
    });
    return () => controller.abort();
  }, [api, refreshKey, refresh]);
  useEffect(() => () => { generation.current++; resumeController.current?.abort(); pendingCallback.current?.(false); }, []);

  // Progress comes from RunPanel's one poller and overrides a possibly older list snapshot.
  const visible = runs?.map(run => activeRun?.run_id === run.run_id ? {
    ...activeRun, totals: { cost_usd: activeRun.progress.cost_usd, failures: activeRun.progress.failures },
  } : run) ?? [];
  const active = runActive || visible.some(run => run.state === "running");
  const selectedDataset = visible.find(run => run.run_id === selected[0])?.dataset;
  async function resume(run: RunSummary) {
    if (active || resumePending.current) return;
    resumePending.current = true; pendingCallback.current?.(true);
    generation.current++; listController.current?.abort();
    const controller = new AbortController(); resumeController.current = controller;
    setResuming(run.run_id); setError(null);
    const result = await api.resumeRun(run.run_id, { signal: controller.signal });
    if (controller.signal.aborted) return;
    resumePending.current = false; pendingCallback.current?.(false); setResuming(null);
    if (!result.ok) { setError(result.error); return; }
    setRuns(previous => previous?.map(value => value.run_id === result.value.run_id ? result.value : value) ?? [result.value]);
    onResume(result.value);
  }
  function toggle(run: RunSummary) {
    setSelected(previous => previous.includes(run.run_id) ? previous.filter(id => id !== run.run_id)
      : previous.length < 2 && (!selectedDataset || selectedDataset === run.dataset) ? [...previous, run.run_id] : previous);
  }
  return <section className="eval-panel" aria-labelledby="eval-runs-title">
    <h2 id="eval-runs-title">Runs</h2>
    <button type="button" onClick={() => setRefresh(value => value + 1)}>Refresh</button>{" "}
    <button type="button" disabled={selected.length !== 2} onClick={() => onCompare(selected[0], selected[1])}>Compare selected ({selected.length})</button>
    {error && <div role="alert"><EvalErrorMessage error={error} /></div>}
    {runs === null ? !error && <p>Loading runs…</p> : visible.length === 0 ? <p>No runs yet. Start one above.</p> :
      <table className="eval-table" aria-label="Runs">
        <thead><tr>{["Select", "Date", "Dataset", "Split", "N", "Schema", "State", "Cost", "Failures", "Actions"].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
        <tbody>{visible.map(run => <tr key={run.run_id} onClick={event => {
          if (event.target instanceof Element && event.target.closest("input,button,a,label")) return;
          onOpenRun(run.run_id);
        }}>
          <td><input type="checkbox" aria-label={`Select ${run.run_id}`} checked={selected.includes(run.run_id)}
            disabled={!selected.includes(run.run_id) && (selected.length >= 2 || selectedDataset !== undefined && selectedDataset !== run.dataset)} onChange={() => toggle(run)} /></td>
          <td><button type="button" className="eval-run-link" onClick={() => onOpenRun(run.run_id)}>{run.created_at}</button></td>
          <td>{run.dataset}</td>
          <td>{run.split}</td>
          <td>{run.n_items}</td>
          <td>{run.schema_version ?? "—"}</td>
          <td><span className="eval-state">{run.state === "aborted_cost" ? "aborted: cost cap" : run.state}</span></td>
          <td>{run.totals.cost_usd === null ? "—" : `$${run.totals.cost_usd.toFixed(2)}`}</td>
          <td>{run.totals.failures}</td>
          <td>{resumable(run) && <button type="button" disabled={active || resuming !== null} onClick={() => void resume(run)}>{resuming === run.run_id ? "Resuming…" : "Resume"}</button>}</td>
        </tr>)}</tbody>
      </table>}
  </section>;
}
