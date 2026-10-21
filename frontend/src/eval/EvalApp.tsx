import { useCallback, useEffect, useRef, useState } from "react";
import { getConfig } from "../config";
import { createEvalApi, type EvalApi } from "./evalApi";
import type { EvalError } from "./evalTypes";
import { ServerBanner } from "./ServerBanner";
import "./eval.css";

export type EvalView =
  | { view: "list" }
  | { view: "run"; runId: string }
  | { view: "item"; runId: string; itemId: string }
  | { view: "compare"; a: string; b: string };

export function ViewSlot({ view }: { view: Exclude<EvalView, { view: "list" }> }) {
  const heading = view.view === "run" ? "Run detail" : view.view === "item" ? "Item detail" : "Compare";
  return <section className="eval-panel" aria-labelledby="eval-view-title">
    <h2 id="eval-view-title">{heading} — coming in D2</h2>
    {view.view === "compare" ? <p>Runs: {view.a} and {view.b}</p> : <>
      <p>Run: {view.runId}</p>
      {view.view === "item" && <p>Item: {view.itemId}</p>}
    </>}
  </section>;
}

export default function EvalApp({ api: suppliedApi, initialView = { view: "list" } }: { api?: EvalApi; initialView?: EvalView }) {
  const [api] = useState(() => suppliedApi ?? createEvalApi({ fetch: globalThis.fetch, baseUrl: getConfig().evalBase }));
  const [view] = useState<EvalView>(initialView);
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

  return <main className="eval-app" aria-label="Evaluation">
    <h1>Eval</h1>
    {checking && <p role="status">Checking eval server…</p>}
    {healthError && <ServerBanner error={healthError} onRetry={checkHealth} />}
    {view.view === "list" ? <div className="eval-sections">
      <section className="eval-panel" aria-labelledby="eval-run-title">
        <h2 id="eval-run-title">Run</h2>
        <p>Run controls are coming in the next implementation task.</p>
      </section>
      <section className="eval-panel" aria-labelledby="eval-runs-title">
        <h2 id="eval-runs-title">Runs</h2>
        <p>The runs list is coming in the next implementation task.</p>
      </section>
    </div> : <ViewSlot view={view} />}
  </main>;
}
