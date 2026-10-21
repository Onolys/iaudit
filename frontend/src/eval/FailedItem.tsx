import type { ValidationIssue } from "../contract";

const isIssue = (value: unknown): value is ValidationIssue => typeof value === "object" && value !== null
  && "path" in value && typeof value.path === "string" && "message" in value && typeof value.message === "string";

export function FailedItem({ failure }: { failure: Record<string, unknown> | null }) {
  const issues = Array.isArray(failure?.issues) ? failure.issues.filter(isIssue) : [];
  return <section aria-label="Failed item">
    <h3>Item failed</h3>
    <dl>
      {typeof failure?.kind === "string" && <><dt>Failure kind</dt><dd>{failure.kind}</dd></>}
      {typeof failure?.http_status === "number" && <><dt>HTTP status</dt><dd>{failure.http_status}</dd></>}
      {typeof failure?.error_code === "string" && <><dt>Error code</dt><dd>{failure.error_code}</dd></>}
      {typeof failure?.message === "string" && <><dt>Message</dt><dd>{failure.message}</dd></>}
    </dl>
    {issues.length > 0 && <ul>{issues.slice(0, 50).map((issue, index) => <li key={index}>{issue.path}: {issue.message}</li>)}
      {issues.length > 50 && <li>and {issues.length - 50} more</li>}
    </ul>}
    <p>No response was saved. Resume the run to retry.</p>
  </section>;
}
