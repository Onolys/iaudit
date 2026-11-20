import { useState } from "react";
import type { Evidence, GlobalScore, PauditResult, ResultWarning, Summary, SummaryStat } from "./types";

const fmt = (n: number | null | undefined) => (n === null || n === undefined ? "-" : String(Math.round(n * 100) / 100));
const spread = (s: { min: number | null; max: number | null }) => (s.min === s.max ? "" : ` (${fmt(s.min)} to ${fmt(s.max)})`);

function Warnings({ items }: { items: ResultWarning[] }) {
  if (items.length === 0) return <p>No warnings.</p>;
  return (
    <ul>
      {items.map((w, i) => (
        <li key={i}>
          <strong>{w.code}</strong>{w.severity ? ` [${w.severity}]` : ""}{w.item_id ? ` (${w.item_id})` : ""}
          {w.detail ? ` - ${w.detail}` : ""}
        </li>
      ))}
    </ul>
  );
}

function Level({ s }: { s: Pick<SummaryStat, "label" | "reference"> | Summary }) {
  return (
    <>
      <td>{s.label ? <span className={`paudit-label-${s.label}`}>{s.label}</span> : "-"}</td>
      <td>{s.reference ? `fair ${fmt(s.reference.fair)}, good ${fmt(s.reference.good)}` : "-"}</td>
    </>
  );
}

function Cited({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return <p>No cited lines.</p>;
  return (
    <ul className="paudit-cited">
      {evidence.map((e, i) => <li key={i}>{`${e.turn_id}: "${e.quote}"`}</li>)}
    </ul>
  );
}

function Global({ id, g, mean }: { id: string; g: GlobalScore | undefined; mean: string }) {
  return (
    <section aria-label={`Global ${id}`}>
      <h3>{id}</h3>
      <p>Mean {mean}{g ? <>; this run: {g.score} ({g.source})</> : null}</p>
      {g ? <><p>{g.reason}</p><Cited evidence={g.evidence} /></> : null}
    </section>
  );
}

export default function ResultView({ result }: { result: PauditResult }) {
  const [runIndex, setRunIndex] = useState(result.aggregate.representative_run);
  const run = result.results.find(r => r.run_index === runIndex) ?? result.results[0];
  const { aggregate, run_info: info } = result;
  const allWarnings = [...result.warnings, ...run.warnings];
  return (
    <div data-testid="paudit-result">
      <h2>Result</h2>
      <p>
        Clinician speaker {result.subject_speaker}; {result.n_runs} run{result.n_runs === 1 ? "" : "s"}; language {result.language}
        {result.change_goal ? `; change goal: ${result.change_goal}` : ""}
      </p>
      {result.results.length > 1 ? (
        <label>Show run{" "}
          <select value={run.run_index} onChange={e => setRunIndex(Number(e.target.value))}>
            {result.results.map(r => (
              <option key={r.run_index} value={r.run_index}>
                {r.run_index + 1}{r.run_index === aggregate.representative_run ? " (representative)" : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <section aria-label="Utterances">
        <h2>Utterances</h2>
        <table className="paudit-table" aria-label="Utterances">
          <thead><tr><th>Turn</th><th>Code</th><th>Quote</th><th>Rationale</th></tr></thead>
          <tbody>
            {run.instances.map(i => (
              <tr key={i.id} className={i.counted ? undefined : "uncounted"}>
                <td>{i.turn_id}</td>
                <td>{i.code ?? "uncoded"}{!i.counted && i.uncounted_reason ? ` (not counted: ${i.uncounted_reason})` : ""}</td>
                <td>{i.quote}</td>
                <td>{i.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-label="Counts">
        <h2>Counts</h2>
        <table className="paudit-table" aria-label="Counts">
          <thead><tr><th>Code</th><th>Mean</th></tr></thead>
          <tbody>
            {Object.entries(aggregate.counts).map(([code, s]) => (
              <tr key={code}><td>{code}</td><td>{fmt(s.mean)}{spread(s)}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-label="Summaries">
        <h2>Summary scores</h2>
        <table className="paudit-table" aria-label="Summary scores">
          <thead><tr><th>Score</th><th>Mean</th><th>Level</th><th>Reference levels</th></tr></thead>
          <tbody>
            {Object.entries(aggregate.summaries).map(([id, s]) => (
              <tr key={id}><td>{id}</td><td>{fmt(s.mean)}{spread(s)}</td><Level s={s} /></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-label="Global scores">
        <h2>Global scores</h2>
        {Object.entries(aggregate.globals).map(([id, s]) => (
          <Global key={id} id={id} g={run.globals[id]} mean={fmt(s.mean) + spread(s)} />
        ))}
      </section>

      <section aria-label="Warnings">
        <h2>Warnings</h2>
        <Warnings items={allWarnings} />
      </section>

      <section aria-label="Run info">
        <h2>Run info</h2>
        <dl className="paudit-runinfo">
          <dt>Engine</dt><dd>{info.engine} {info.code_version}</dd>
          {info.pack ? <><dt>Pack</dt><dd>{info.pack.id}@{info.pack.version} ({info.pack.hash})</dd></> : null}
          {info.preset ? <><dt>Preset</dt><dd>{info.preset}</dd></> : null}
          <dt>Runs</dt><dd>{info.n_runs ?? result.n_runs}</dd>
          {info.routes ? <><dt>Models</dt><dd>{Object.entries(info.routes).map(([k, r]) => `${k}: ${r.litellm_id}`).join("; ")}</dd></> : null}
          {info.usage ? (
            <><dt>Usage</dt><dd>{`${info.usage.calls ?? 0} calls, ${info.usage.input_tokens ?? 0} in / ${info.usage.output_tokens ?? 0} out tokens, cost ${info.usage.cost_usd ?? "n/a"}`}</dd></>
          ) : null}
          {result.request_id ? <><dt>Request id</dt><dd>{result.request_id}</dd></> : null}
        </dl>
      </section>
    </div>
  );
}
