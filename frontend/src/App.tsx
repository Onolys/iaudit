import { useState } from "react";
import "./tokens/tokens.css";
import "./app/app.css";
import { getConfig } from "./config";
import EvalApp from "./eval/EvalApp";
import { PRODUCTS } from "./products";
import { PRODUCT_VIEWS } from "./productViews";
import type { ProductId } from "./products";
import type { AuditDeps } from "./transport/runAudit";
import type { EvalApi } from "./eval/evalApi";

export default function App({ deps, evalApi }: { deps?: AuditDeps; evalApi?: EvalApi }) {
  const [mode, setMode] = useState<ProductId | "eval">(PRODUCTS[0].id);
  // Deployed builds set VITE_EVAL_ENABLED=false: no Eval tab, EvalApp never mounts, so no eval calls.
  const { evalEnabled } = getConfig();
  const showEval = evalEnabled && mode === "eval";
  const View = showEval ? null : PRODUCT_VIEWS[mode === "eval" ? PRODUCTS[0].id : mode];
  return (
    <div className="app-shell">
      <nav className="app-mode-switch" aria-label="Workspace">
        {PRODUCTS.map(product => (
          <button key={product.id} type="button" aria-pressed={mode === product.id} onClick={() => setMode(product.id)}>{product.label}</button>
        ))}
        {evalEnabled ? (
          <button type="button" aria-pressed={mode === "eval"} onClick={() => setMode("eval")}>Eval</button>
        ) : null}
      </nav>
      <div className="app-content">
        {showEval ? <EvalApp api={evalApi} /> : View ? <View deps={deps} /> : null}
      </div>
    </div>
  );
}
