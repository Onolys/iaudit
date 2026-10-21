import type { EvalError } from "./evalTypes";

/** Server strings are rendered as text, including structured API error details. */
export function EvalErrorMessage({ error }: { error: EvalError }) {
  switch (error.kind) {
    case "unreachable": return <p>Eval server not reachable</p>;
    case "timeout": return <p>Eval request timed out after {error.seconds} seconds</p>;
    case "cancelled": return <p>Eval request cancelled</p>;
    case "bad_body": return <p>{error.message}</p>;
    case "api": return <div className="eval-error">
      <p>{error.message}</p>
      {error.detail !== undefined && <pre>{typeof error.detail === "string" ? error.detail : JSON.stringify(error.detail, null, 2)}</pre>}
    </div>;
  }
}

/** Callers keep their last data visible while this banner reports connection loss. */
export function ServerBanner({ error, lostContact = false, onRetry }: { error?: EvalError; lostContact?: boolean; onRetry?: () => void }) {
  return <div className="eval-banner" role="alert">
    <p>{lostContact ? "Lost contact with eval server — retrying" : "Eval server not reachable"}</p>
    {error && error.kind !== "unreachable" && <EvalErrorMessage error={error} />}
    {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
  </div>;
}
