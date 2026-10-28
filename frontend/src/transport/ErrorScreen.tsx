import type { ReactNode } from "react";
import type { ValidationIssue } from "../contract";
import { isRetryable } from "./errors";
import type { LoadError } from "./errors";
import type { ErrorBody } from "./errorBody";

const MAX_ISSUES = 50;

function Issues({ issues }: { issues: ValidationIssue[] }) {
  const more = issues.length - MAX_ISSUES;
  return (
    <ul>
      {issues.slice(0, MAX_ISSUES).map((issue, i) => (
        <li key={i}>
          {issue.path}: {issue.message}
        </li>
      ))}
      {more > 0 ? <li>and {more} more</li> : null}
    </ul>
  );
}

function HttpDetails({ message, details }: Partial<ErrorBody>) {
  return (
    <>
      {message ? <p>{message}</p> : null}
      {details?.length ? (
        <ul>{details.map((detail, i) => <li key={i}>{detail.message}</li>)}</ul>
      ) : null}
    </>
  );
}

const RESPONSE_REASON = {
  empty: "The service returned an empty response.",
  not_json: "The service response is not valid JSON.",
  not_object: "The service response is not a JSON object.",
  schema: "The service response does not match the audit response schema.",
  duplicate_claim_id: "The service response contains a duplicate claim id.",
  duplicate_evidence_id: "The service response contains a duplicate evidence id within a claim.",
} as const;

function describe(error: LoadError): { title: string; detail: ReactNode } {
  switch (error.kind) {
    case "invalid_request_file":
      return {
        title: "Invalid request file",
        detail:
          error.reason === "empty" ? (
            <p>The file is empty.</p>
          ) : error.reason === "not_json" ? (
            <p>The file is not valid JSON{error.message ? `: ${error.message}` : "."}</p>
          ) : (
            <Issues issues={error.issues ?? []} />
          ),
      };
    case "config_missing":
      return { title: "Audit service not configured", detail: <p>VITE_AUDIT_URL is not set; mock mode is off.</p> };
    case "mock_no_match":
      return { title: "No mock audit for this request", detail: <p>request_id: {error.requestId ?? "none"}</p> };
    case "network":
      return {
        title: "Couldn't reach the audit service.",
        detail: (
          <>
            <p>{error.url}</p>
            <p>The service may be down, the URL wrong, or the request blocked by CORS.</p>
          </>
        ),
      };
    case "timeout":
      return { title: "Request timed out", detail: <p>No response after {error.seconds} s.</p> };
    case "cancelled":
      return { title: "Cancelled.", detail: null };
    case "http_4xx":
      return { title: `Request rejected (${error.status})`, detail: <HttpDetails message={error.message} details={error.details} /> };
    case "http_5xx":
      return { title: `Audit service error (${error.status}).`, detail: <HttpDetails message={error.message} details={error.details} /> };
    case "invalid_response":
      return {
        title: "Invalid audit response",
        detail: (
          <>
            <p>
              {RESPONSE_REASON[error.reason]}
              {error.reason === "duplicate_claim_id" && error.claimId ? ` (${error.claimId})` : ""}
              {error.reason === "duplicate_evidence_id" && error.claimId ? ` (${error.claimId}/${error.evidenceId})` : ""}
              {error.reason === "not_json" && error.message ? ` ${error.message}` : ""}
            </p>
            {error.issues ? <Issues issues={error.issues} /> : null}
          </>
        ),
      };
    case "request_id_mismatch":
      return {
        title: "Response doesn't match this request.",
        detail: (
          <p>
            Expected request_id {error.expected}, received {error.received ?? "none"}.
          </p>
        ),
      };
  }
}

// Network, timeout, cancelled and 5xx offer only Retry; every other kind needs a different file.
const RETRY_ONLY = new Set<LoadError["kind"]>(["network", "timeout", "cancelled", "http_5xx"]);

export function ErrorScreen({
  error,
  onRetry,
  onChooseFile,
}: {
  error: LoadError;
  onRetry?: () => void;
  onChooseFile?: () => void;
}) {
  const { title, detail } = describe(error);
  return (
    <div role="alert">
      <h2>{title}</h2>
      {detail}
      <div>
        {onRetry && isRetryable(error) ? (
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        {!onChooseFile || RETRY_ONLY.has(error.kind) ? null : (
          <button type="button" onClick={onChooseFile}>
            Choose another file
          </button>
        )}
      </div>
    </div>
  );
}
