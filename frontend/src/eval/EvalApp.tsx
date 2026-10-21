import { useCallback, useEffect, useRef, useState } from "react";
import { getConfig } from "../config";
import { createEvalApi, type EvalApi } from "./evalApi";
import type { EvalError, RunDetail as RunData } from "./evalTypes";
import { ServerBanner } from "./ServerBanner";
import { RunsList } from "./RunsList";
import { RunPanel } from "./RunPanel";
import { RunDetail } from "./RunDetail";
import { ItemDetail } from "./ItemDetail";
import { CompareView } from "./CompareView";
import "./eval.css";

export type EvalView =
  | { view: "list" }
  | { view: "run"; runId: string }
  | { view: "item"; runId: string; itemId: string; from: "run" }
  | { view: "item"; runId: string; itemId: string; from: "compare"; cmp: [string, string] }
  | { view: "compare"; a: string; b: string };

export default function EvalApp({ api: suppliedApi, initialView = { view: "list" } }: { api?: EvalApi; initialView?: EvalView }) {
  const [api] = useState(() => suppliedApi ?? createEvalApi({ fetch: globalThis.fetch, baseUrl: getConfig().evalBase }));
  const [view, setView] = useState<EvalView>(initialView);
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeRun, setActiveRun] = useState<RunData | null>(null);
  const [runActive, setRunActive] = useState(false);
  const [resumePending, setResumePending] = useState(false);
  const [attachment, setAttachment] = useState<{ runId: string }>();
  const refreshRuns = useCallback(() => setRefreshKey(value => value + 1), []);
  const [healthError, setHealthError] = useState<EvalError | null>(null);
  const [checking, setChecking] = useState(true);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);

  const checkHealth = useCallback(() => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    const attempt = ++generation.current;
    setChecking(true);
    void api.health({ signal: current.signal }).then(result => {
      if (generation.current !== attempt || current.signal.aborted) return;
      setChecking(false);
      setHealthError(result.ok ? null : result.error);
    });
  }, [api]);

  useEffect(() => {
    checkHealth();
    return () => {
      generation.current++;
      controller.current?.abort();
    };
  }, [checkHealth]);

  const backToList = () => {
    setActiveRun(null); setRunActive(false); setResumePending(false); setAttachment(undefined);
    setView({ view: "list" });
  };
  return <main className="eval-app" aria-label="Evaluation">
    <h1>Eval</h1>
    {checking && <p role="status">Checking eval server…</p>}
    {healthError && <ServerBanner error={healthError} onRetry={checkHealth} />}
    {view.view === "list" ? <div className="eval-sections">
      <RunPanel api={api} blocked={resumePending} attachment={attachment} onRunActiveChange={setRunActive} onActiveRunChange={setActiveRun} onRunsChanged={refreshRuns} />
      <RunsList api={api} onResumePendingChange={setResumePending} refreshKey={refreshKey} activeRun={activeRun} runActive={runActive}
        onResume={run => { setRunActive(true); setActiveRun(null); setAttachment({ runId: run.run_id }); refreshRuns(); }}
        onOpenRun={runId => setView({ view: "run", runId })}
        onCompare={(a, b) => setView({ view: "compare", a, b })} />
    </div> : view.view === "run" ? <RunDetail api={api} runId={view.runId} onBack={backToList}
      onOpenItem={itemId => setView({ view: "item", runId: view.runId, itemId, from: "run" })} />
      : view.view === "item" ? <ItemDetail api={api} runId={view.runId} itemId={view.itemId}
        backLabel={view.from === "compare" ? "Back to comparison" : "Back to run"}
        onBack={() => setView(view.from === "compare" ? { view: "compare", a: view.cmp[0], b: view.cmp[1] } : { view: "run", runId: view.runId })} />
      : <CompareView api={api} aRunId={view.a} bRunId={view.b} onBack={backToList}
        onOpenItem={(runId, itemId) => setView({ view: "item", runId, itemId, from: "compare", cmp: [view.a, view.b] })} />}
  </main>;
}
