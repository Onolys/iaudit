import { useEffect, useId, useState } from "react";
import type { EvalApi } from "./evalApi";
import type { EvalError, ItemFilter, ItemPage } from "./evalTypes";
import { EvalErrorMessage } from "./ServerBanner";
import "./item-list.css";

interface ItemListState { runId: string; page: ItemPage | null; loading: boolean; error: EvalError | null }

/** One high-limit request per filter; keep the last rows visible while that filter reloads. */
export function ItemList({ api, runId, onOpenItem }: { api: EvalApi; runId: string; onOpenItem: (itemId: string) => void }) {
  const filterName = useId();
  const [filter, setFilter] = useState<ItemFilter>("all");
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<ItemListState>({ runId, page: null, loading: true, error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState(previous => ({ runId, page: previous.runId === runId ? previous.page : null, loading: true, error: null }));
    void api.listItems(runId, { filter, limit: 10_000 }, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      setState(previous => result.ok
        ? { runId, page: result.value, loading: false, error: null }
        : { ...previous, loading: false, error: result.error });
    });
    return () => controller.abort();
  }, [api, runId, filter, retry]);

  const page = state.runId === runId ? state.page : null;
  const loading = state.runId !== runId || state.loading;
  return <section className="eval-item-list" aria-label="Items">
    <h3>Items</h3>
    <fieldset><legend>Filter items</legend>{(["all", "mismatch", "failed"] as const).map(value =>
      <label key={value}><input type="radio" name={filterName} value={value} checked={filter === value} onChange={() => setFilter(value)} />{value}</label>,
    )}</fieldset>
    {loading && <p role="status">Loading items…</p>}
    {state.runId === runId && state.error && <div role="alert"><EvalErrorMessage error={state.error} /><button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></div>}
    {page && page.items.length > 0 && <table className={`eval-table${loading ? " is-loading" : ""}`} aria-label="Run items" aria-busy={loading}>
      <thead><tr>{["Item", "Gold", "Ours", "Match", "Status"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
      <tbody>{page.items.map(item => <tr key={item.item_id} onClick={() => onOpenItem(item.item_id)}>
        <td><button type="button" onClick={event => { event.stopPropagation(); onOpenItem(item.item_id); }}>{item.label ?? item.item_id}</button></td>
        <td>{item.gold ?? "-"}</td><td>{item.pred ?? "-"}</td>
        <td aria-label={item.match === true ? "Match" : item.match === false ? "Mismatch" : "Unknown"}>{item.match === true ? "✓" : item.match === false ? "✗" : "-"}</td>
        <td>{item.status === "failed" ? <span className="chip">failed</span> : "-"}</td>
      </tr>)}</tbody>
    </table>}
    {page?.items.length === 0 && !loading && !state.error && <p>No items match this filter.</p>}
  </section>;
}
