import { useEffect, useRef, useState, type FormEvent } from "react";
import type { EvalApi } from "./evalApi";
import type { DatasetMeta, DatasetSummary, Estimate, EvalError, RunRequest } from "./evalTypes";
import { EvalErrorMessage } from "./ServerBanner";

const datasetStorageKey = "iaudit.eval.dataset";
const validN = (value: string) => value.trim() === "" || (/^\d+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) >= 1);

/** Pre-run inputs. The lifecycle layer supplies onRun to start and monitor runs. */
export function RunPanel({ api, onRun }: { api: EvalApi; onRun?: (request: RunRequest) => void }) {
  const [datasets, setDatasets] = useState<DatasetSummary[] | null>(null);
  const [dataset, setDataset] = useState("");
  const [meta, setMeta] = useState<DatasetMeta | null>(null);
  const [split, setSplit] = useState("");
  const [n, setN] = useState("");
  const [cap, setCap] = useState("");
  const capEdited = useRef(false);
  const [clampNote, setClampNote] = useState("");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [loadError, setLoadError] = useState<EvalError | null>(null);
  const [metaError, setMetaError] = useState<EvalError | null>(null);
  const [estimateError, setEstimateError] = useState<EvalError | null>(null);
  const [retry, setRetry] = useState(0);
  const nValid = validN(n);
  const capValid = cap.trim() === "" || (Number.isFinite(Number(cap)) && Number(cap) > 0);
  const selectedMeta = meta?.name === dataset ? meta : null;

  useEffect(() => {
    const controller = new AbortController();
    setLoadError(null);
    void api.listDatasets({ signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      if (!result.ok) { setLoadError(result.error); return; }
      setDatasets(result.value);
      let remembered: string | null = null;
      try { remembered = localStorage.getItem(datasetStorageKey); } catch { /* Storage is optional. */ }
      setDataset(result.value.find(item => item.name === remembered)?.name ?? result.value[0]?.name ?? "");
    });
    return () => controller.abort();
  }, [api, retry]);

  useEffect(() => {
    if (!dataset) return;
    const controller = new AbortController();
    setMeta(null); setSplit(""); setMetaError(null); setEstimate(null); setClampNote("");
    if (!capEdited.current) setCap("");
    try { localStorage.setItem(datasetStorageKey, dataset); } catch { /* Storage is optional. */ }
    void api.getDataset(dataset, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      if (!result.ok) { setMetaError(result.error); return; }
      setMeta(result.value);
      setSplit(result.value.splits.some(item => item.name === result.value.default_split)
        ? result.value.default_split! : result.value.splits[0]?.name ?? "all");
    });
    return () => controller.abort();
  }, [api, dataset, retry]);

  useEffect(() => {
    setEstimate(null); setEstimateError(null);
    if (!capEdited.current) setCap("");
    if (!selectedMeta || !split || !nValid) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void api.estimate({ dataset, split, ...(n.trim() === "" ? {} : { n: Number(n) }) }, { signal: controller.signal }).then(result => {
        if (controller.signal.aborted) return;
        if (!result.ok) { setEstimateError(result.error); return; }
        setEstimate(result.value);
        if (!capEdited.current) {
          const cost = result.value.est_cost_usd;
          setCap(cost === null || cost <= 0 ? "" : (Math.ceil(cost * 150) / 100).toFixed(2));
        }
      });
    }, 400);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [api, dataset, selectedMeta, split, n, nValid]);

  function clampN() {
    if (!selectedMeta || !nValid || n.trim() === "") return;
    const sizes = selectedMeta.splits;
    const size = split === "all"
      ? sizes.every(item => item.size !== null) ? sizes.reduce((sum, item) => sum + item.size!, 0) : null
      : sizes.find(item => item.name === split)?.size ?? null;
    if (size !== null && size >= 1 && Number(n) > size) { setN(String(size)); setClampNote(`N clamped to ${size}`); }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedMeta || !split || !nValid || !capValid) return;
    onRun?.({ dataset, split, ...(n.trim() === "" ? {} : { n: Number(n) }), ...(cap.trim() === "" ? {} : { max_cost_usd: Number(cap) }) });
  }

  return <section className="eval-panel" aria-labelledby="eval-run-title">
    <h2 id="eval-run-title">Run</h2>
    {(loadError || metaError) && <><EvalErrorMessage error={(loadError || metaError)!} /><button type="button" onClick={() => setRetry(value => value + 1)}>Retry run form</button></>}
    {datasets === null ? !loadError && <p>Loading datasets…</p> : datasets.length === 0 ? <p>No datasets in eval/datasets/</p> :
      <form className="eval-run-form" onSubmit={submit} noValidate>
        <label htmlFor="eval-dataset">Dataset</label>
        <select id="eval-dataset" value={dataset} onChange={event => setDataset(event.target.value)}>
          {datasets.map(item => <option key={item.name} value={item.name}>{item.title}</option>)}
        </select>
        <label htmlFor="eval-split">Split</label>
        <select id="eval-split" value={split} disabled={!selectedMeta} onChange={event => { setSplit(event.target.value); setClampNote(""); }}>
          {!selectedMeta && <option value="">Loading splits…</option>}
          {selectedMeta?.splits.filter(item => item.name !== "all").map(item => <option key={item.name} value={item.name}>{item.name}</option>)}
          {selectedMeta && <option value="all">all</option>}
        </select>
        {split === "test" && selectedMeta?.test_split_note && <p>{selectedMeta.test_split_note}</p>}
        <label htmlFor="eval-n">N</label>
        <input id="eval-n" inputMode="numeric" value={n} aria-invalid={!nValid} aria-describedby="eval-n-help" onChange={event => { setN(event.target.value); setClampNote(""); }} onBlur={clampN} />
        <p id="eval-n-help">Blank = whole split.</p>
        {!nValid && <p className="eval-error">N must be an integer of at least 1.</p>}
        {clampNote && <p>{clampNote}</p>}
        {estimate && <p>{estimate.est_cost_usd === null ? estimate.note || "Cost unknown — run a pilot (e.g. N=5) first" : `~$${estimate.est_cost_usd.toFixed(2)} for ${estimate.n_items} items (rough)`}</p>}
        {estimateError && <EvalErrorMessage error={estimateError} />}
        <label htmlFor="eval-cap">Max cost (USD)</label>
        <input id="eval-cap" inputMode="decimal" value={cap} aria-invalid={!capValid} aria-describedby="eval-cap-help" onChange={event => { capEdited.current = true; setCap(event.target.value); }} />
        <p id="eval-cap-help">Optional. Blank = no cap.</p>
        {!capValid && <p className="eval-error">Max cost must be greater than 0, or blank for no cap.</p>}
        <button type="submit" disabled={!selectedMeta || !split || !nValid || !capValid}>Run</button>
      </form>}
  </section>;
}
