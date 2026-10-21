import { Fragment } from "react";
import type { MetricsReport } from "./evalTypes";
import { toMetricRows } from "./toMetricRows";
import type { MetricValue } from "./toMetricRows";
import "./metrics.css";

const referenceDisclaimer = "paper-reported, different model & date";
const format = (value: number | null) => value === null ? "-" : String(Number(value.toFixed(4)));

function Values({ entry }: { entry?: MetricValue }) {
  if (!entry) return <><td>-</td><td>-</td><td>-</td></>;
  const clusterHint = `n_clusters: ${entry.clusters}`;
  return <>
    <td title={clusterHint}>{format(entry.value)}</td>
    <td title={clusterHint}>{entry.n}</td>
    <td title={entry.intervalStatus === "ok" ? clusterHint : entry.intervalStatus}>
      {entry.intervalStatus === "ok" && entry.interval ? `[${entry.interval.map(format).join(", ")}]` : "-"}
    </td>
  </>;
}

export function MetricsTable({ report }: { report: MetricsReport }) {
  const { groups, failures, diagnostics, referenceCaveats } = toMetricRows(report);
  return <div className="eval-metrics">
    <p>Failures: {failures.failed} of {failures.total}. Primary counts them wrong; secondary excludes them.</p>
    {failures.rates.length > 0 && <ul>{failures.rates.map((rate, index) => <li key={index}>{rate.level} ({rate.slice}) {rate.metric}: {format(rate.value)}</li>)}</ul>}
    {groups.map((group, index) => <section key={`${group.level}/${group.slice}`}>
      {groups[index - 1]?.level !== group.level && <h3>{group.level}</h3>}
      <h4>{group.slice}</h4>
      <table className="eval-table" aria-label={`${group.level}: ${group.slice}`}>
        <thead><tr><th scope="col">Metric</th><th scope="col">Primary value</th><th scope="col">Primary n</th><th scope="col">Primary CI</th><th scope="col">Secondary value</th><th scope="col">Secondary n</th><th scope="col">Secondary CI</th></tr></thead>
        <tbody>{group.rows.map(row => <Fragment key={row.metric}>
          <tr><th scope="row">{row.metric}</th><Values entry={row.primary} /><Values entry={row.secondary} /></tr>
          {row.references.map((reference, referenceIndex) => <tr className="is-reference" key={referenceIndex}>
            <th scope="row" title={[reference.source, reference.note].filter(Boolean).join(" — ")}>
              {row.metric} — <span>{reference.label}</span>{reference.label.includes(referenceDisclaimer) ? null : ` — ${referenceDisclaimer}`}
            </th>
            <td>{format(reference.value)}</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>
          </tr>)}
        </Fragment>)}</tbody>
      </table>
    </section>)}
    {diagnostics.length > 0 && <section>
      <h3>Diagnostics</h3>
      {diagnostics.map(group => <Fragment key={`${group.level}/${group.slice}`}>
        <h4>{group.level} · {group.slice}</h4>
        <table className="eval-table" aria-label={`Diagnostics: ${group.level}, ${group.slice}`}>
          <thead><tr><th scope="col">Metric</th><th scope="col">Value</th><th scope="col">n</th></tr></thead>
          <tbody>{group.rows.map((row, index) => <tr key={index}><th scope="row">{row.metric}</th><td>{format(row.value)}</td><td>{row.n}</td></tr>)}</tbody>
        </table>
      </Fragment>)}
    </section>}
    {referenceCaveats.length > 0 && <details><summary>Reference caveats</summary><ul>{referenceCaveats.map((note, index) => <li key={index}>{note}</li>)}</ul></details>}
  </div>;
}
