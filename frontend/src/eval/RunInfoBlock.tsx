import type { RunDetail, RunTotals } from "./evalTypes";
import "./metrics.css";

type RunInfoInput = Omit<RunDetail, "totals"> & {
  totals?: Partial<RunTotals> & { input_tokens?: number; output_tokens?: number };
};
const object = (value: unknown): Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
const strings = (value: unknown) => Object.entries(object(value)).filter((pair): pair is [string, string] => typeof pair[1] === "string");

/** Run provenance uses the fingerprint captured from the first audit response. */
export function RunInfoBlock({ run }: { run: RunInfoInput }) {
  const info = run.run_info;
  const fingerprint = object(info.fingerprint);
  const models = strings(fingerprint.models);
  const hashes = strings(fingerprint.prompt_hashes);
  return <section className="eval-run-info" aria-label="Run information">
    <h3>Run information</h3>
    <dl>
      <dt>Git commit</dt><dd>{info.git_commit ?? "unknown"}{(info.git_dirty ?? run.git_dirty) ? " (dirty)" : ""}</dd>
      <dt>Models</dt><dd>{models.length ? <ul>{models.map(([tier, model]) => <li key={tier}>{tier}: {model}</li>)}</ul> : "unknown"}</dd>
      <dt>Prompt hashes</dt><dd>{hashes.length ? <ul>{hashes.map(([name, hash]) => <li key={name}>{name}: <span title={hash}>{hash.slice(0, 8)}</span></li>)}</ul> : "unknown"}</dd>
      <dt>Mapping version</dt><dd>{info.mapping_version ?? "unknown"}</dd>
      <dt>Seed</dt><dd>{info.seed ?? run.seed ?? "unknown"}</dd>
      {info.tags && Object.keys(info.tags).length > 0 && <><dt>Tags</dt><dd><ul>{Object.entries(info.tags).map(([key, value]) => <li key={key}>{key}: {typeof value === "string" ? value : JSON.stringify(value)}</li>)}</ul></dd></>}
      <dt>Total cost</dt><dd>{run.totals?.cost_usd == null ? "unknown" : `$${run.totals.cost_usd.toFixed(2)}`}</dd>
    </dl>
    {run.totals?.input_tokens !== undefined && <p>Input tokens: {run.totals.input_tokens}</p>}
    {run.totals?.output_tokens !== undefined && <p>Output tokens: {run.totals.output_tokens}</p>}
    {info.mixed && <p role="note">Warning: mixed fingerprint run.</p>}
    {info.warnings && info.warnings.length > 0 && <ul>{info.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
    {run.split === "test" && <p>Test runs are for reporting, not tuning.</p>}
  </section>;
}
