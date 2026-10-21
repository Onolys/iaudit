import { useEffect, useMemo, useState } from "react";
import { ReviewShell } from "../app/ReviewShell";
import { ErrorScreen } from "../transport/ErrorScreen";
import { buildLoadResult } from "./buildLoadResult";
import type { EvalApi } from "./evalApi";
import type { EvalError, ItemDetail as SavedItem } from "./evalTypes";
import { FailedItem } from "./FailedItem";
import { GoldPanel } from "./gold/GoldPanel";
import { EvalErrorMessage, ServerBanner } from "./ServerBanner";
import "./item-detail.css";

interface ItemState { key: string; item: SavedItem | null; error: EvalError | null; loading: boolean }

/** Saved-item inspection only; validation and review never call the audit service. */
export function ItemDetail({ api, runId, itemId, onBack, backLabel }: {
  api: EvalApi;
  runId: string;
  itemId: string;
  onBack: () => void;
  backLabel: string;
}) {
  const key = JSON.stringify([runId, itemId]);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<ItemState>({ key, item: null, error: null, loading: true });
  useEffect(() => {
    const controller = new AbortController();
    setState({ key, item: null, error: null, loading: true });
    void api.getItem(runId, itemId, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      setState(result.ok
        ? { key, item: result.value, error: null, loading: false }
        : { key, item: null, error: result.error, loading: false });
    });
    return () => controller.abort();
  }, [api, runId, itemId, key, retry]);
  const item = state.key === key ? state.item : null;
  const error = state.key === key ? state.error : null;
  const replay = useMemo(() => item && item.status !== "failed" && !(item.status === "unmapped" && item.response === null)
    ? buildLoadResult(item.request, item.response) : null, [item]);
  const retryLoad = () => setRetry(value => value + 1);

  return <div className="eval-item-detail">
    <div className="eval-item-back"><button type="button" onClick={onBack}>{backLabel}</button><span>{runId} — {itemId}</span></div>
    {(state.key !== key || state.loading) && <p role="status">Loading item…</p>}
    {error && (error.kind === "api"
      ? <div role="alert"><EvalErrorMessage error={error} /><button type="button" onClick={retryLoad}>Retry</button></div>
      : <ServerBanner error={error} onRetry={retryLoad} />)}
    {item && <>
      <GoldPanel goldKind={item.gold_kind} gold={item.gold} />
      {item.status === "unmapped" && <p>This item could not be mapped for scoring.</p>}
      {item.status === "failed" ? <FailedItem failure={item.failure} />
        : replay ? replay.ok
          ? <ReviewShell key={key} result={replay.value} headerProps={{ mock: false, fileName: `${runId} - ${itemId}`, requestId: replay.value.request.request_id }} />
          : <ErrorScreen error={replay.error} />
        : <p>No saved audit response is available.</p>}
    </>}
  </div>;
}
