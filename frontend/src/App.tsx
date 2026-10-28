import { useRef, useState } from "react";
import "./tokens/tokens.css";
import "./app/app.css";
import { Header } from "./app/Header";
import { ReviewShell } from "./app/ReviewShell";
import { ErrorScreen, LoadingView, useAuditLoader } from "./transport";
import type { LoadResult } from "./transport";
import type { AuditDeps } from "./transport/runAudit";
import EvalApp from "./eval/EvalApp";
import { PRODUCTS } from "./products";
import type { ProductId } from "./products";
import type { EvalApi } from "./eval/evalApi";

export default function App({ deps, evalApi }: { deps?: AuditDeps; evalApi?: EvalApi }) {
  const [mode, setMode] = useState<ProductId | "eval">(PRODUCTS[0].id);
  return (
    <div className="app-shell">
      <nav className="app-mode-switch" aria-label="Workspace">
        {PRODUCTS.map(product => (
          <button key={product.id} type="button" aria-pressed={mode === product.id} onClick={() => setMode(product.id)}>{product.label}</button>
        ))}
        <button type="button" aria-pressed={mode === "eval"} onClick={() => setMode("eval")}>Eval</button>
      </nav>
      <div className="app-content">
        {mode === "eval" ? <EvalApp api={evalApi} /> : <EauditApp deps={deps} />}
      </div>
    </div>
  );
}

function EauditApp({ deps }: { deps?: AuditDeps }) {
  const { state, loadFile, retry, cancel } = useAuditLoader(deps);
  const inputRef = useRef<HTMLInputElement>(null);
  // Each loaded result gets its own id, so a new upload (even of the same file) remounts the review.
  const loadIds = useRef(new WeakMap<LoadResult, number>());
  const nextId = useRef(0);
  const loadIdOf = (result: LoadResult) => {
    if (!loadIds.current.has(result)) loadIds.current.set(result, nextId.current++);
    return loadIds.current.get(result)!;
  };

  const requestId =
    state.status === "ok" ? state.result.request.request_id : state.status === "loading" ? state.requestId : undefined;
  const headerProps = {
    fileName: state.status === "idle" ? undefined : state.fileName,
    requestId,
    mock: state.status === "ok" && state.result.source === "mock",
    inputRef,
    onFile: (file: File) => void loadFile(file),
  };
  const chooseFile = () => inputRef.current?.click();

  if (state.status === "ok") {
    return (
      <div className="app">
        <ReviewShell key={loadIdOf(state.result)} result={state.result} headerProps={headerProps} />
      </div>
    );
  }
  return (
    <div className="app">
      <Header {...headerProps} />
      <div className="app-message">
        {state.status === "idle" ? <p>Upload a request JSON file to begin.</p> : null}
        {state.status === "loading" ? <LoadingView requestId={state.requestId} onCancel={cancel} /> : null}
        {state.status === "error" ? (
          <ErrorScreen error={state.error} onRetry={retry} onChooseFile={chooseFile} />
        ) : null}
      </div>
    </div>
  );
}
