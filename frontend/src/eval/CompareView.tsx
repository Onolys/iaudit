import { useEffect, useState } from "react";
import type { EvalApi } from "./evalApi";
import type { Comparison, EvalError } from "./evalTypes";
import { EvalErrorMessage, ServerBanner } from "./ServerBanner";
import "./compare.css";

interface ComparisonState { key: string; data: Comparison | null; error: EvalError | null; loading: boolean }
const number = (value: number | null) => value === null ? "-" : String(Number(value.toFixed(4)));
const signed = (value: number | null) => value === null ? "-" : `${value >= 0 ? "+" : ""}${number(value)}`;

export function CompareView({ api, aRunId, bRunId, onOpenItem, onBack }: {
  api: EvalApi;
  aRunId: string;
  bRunId: string;
  onOpenItem: (runId: string, itemId: string) => void;
  onBack: () => void;
}) {
  const key = JSON.stringify([aRunId, bRunId]);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<ComparisonState>({ key, data: null, error: null, loading: true });
  useEffect(() => {
    const controller = new AbortController();
    setState({ key, data: null, error: null, loading: true });
    void api.compare(aRunId, bRunId, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      setState(result.ok
        ? { key, data: result.value, error: null, loading: false }
        : { key, data: null, error: result.error, loading: false });
    });
    return () => controller.abort();
  }, [api, aRunId, bRunId, key, retry]);
  const data = state.key === key ? state.data : null;
  const error = state.key === key ? state.error : null;
  const retryLoad = () => setRetry(value => value + 1);
  return <section className="eval-comparison" aria-label="Run comparison">
    <button type="button" onClick={onBack}>Back</button>
    <h2>Compare runs</h2>
    <p>A: {data?.run_a ?? aRunId}</p><p>B: {data?.run_b ?? bRunId}</p>
    {(state.key !== key || state.loading) && <p role="status">Loading comparison…</p>}
    {error && (error.kind === "api"
      ? <div role="alert"><EvalErrorMessage error={error} /><button type="button" onClick={retryLoad}>Retry</button></div>
      : <ServerBanner error={error} onRetry={retryLoad} />)}
    {data && <>
      <p className="eval-shared-count"><strong>n shared = {data.n_shared}</strong></p>
      {data.warnings.length > 0 && <ul>{data.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
      {data.n_shared === 0 ? <p>No shared items</p> : <>
        <table className="eval-table" aria-label="Metric deltas">
          <thead><tr>{["Metric", "Level", "Slice", "Policy", "A", "B", "Delta (B − A)", "Delta CI"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody>{data.deltas.map((entry, index) => <tr key={index}>
            <th scope="row">{entry.metric}</th><td>{entry.level}</td>
            <td>{Object.entries(entry.slice).map(([name, value]) => `${name}: ${String(value)}`).join(", ") || "All items"}</td>
            <td>{entry.policy}</td><td title={`n: ${entry.a.n}`}>{number(entry.a.value)}</td><td title={`n: ${entry.b.n}`}>{number(entry.b.value)}</td>
            <td>{signed(entry.delta)}</td><td title={entry.ci_status === "ok" ? `n_clusters: ${entry.n_clusters}` : entry.ci_status}>
              {entry.ci_status === "ok" && entry.delta_ci ? `[${entry.delta_ci.map(signed).join(", ")}]` : "-"}
            </td>
          </tr>)}</tbody>
        </table>
        <h3>Disagreements</h3>
        {data.disagreements.length === 0 && <p>No disagreements</p>}
        {data.disagreements.map(item => <section key={item.item_id}>
          <h4>{item.item_id}</h4>
          <div className="eval-comparison-actions">
            <button type="button" onClick={() => onOpenItem(aRunId, item.item_id)}>open in A</button>
            <button type="button" onClick={() => onOpenItem(bRunId, item.item_id)}>open in B</button>
          </div>
          <table className="eval-table" aria-label={`Disagreements for ${item.item_id}`}>
            <thead><tr>{["Level", "Unit", "Gold", "A", "B"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
            <tbody>{item.pairs.map((pair, index) => <tr key={index}>
              <td>{pair.level}</td><td>{pair.unit}</td><td>{pair.gold}</td><td>{pair.a ?? "-"}</td><td>{pair.b ?? "-"}</td>
            </tr>)}</tbody>
          </table>
        </section>)}
      </>}
    </>}
  </section>;
}
