import type { MetricEntry, MetricsReport, Slice } from "./evalTypes";

export interface MetricValue {
  value: number | null;
  n: number;
  clusters: number;
  interval: [number, number] | null;
  intervalStatus: "ok" | "few_clusters" | "undefined";
}
export interface MetricRow {
  metric: string;
  primary?: MetricValue;
  secondary?: MetricValue;
  references: { value: number; source: string; label: string; note?: string }[];
}
export interface MetricGroup { level: string; slice: string; rows: MetricRow[] }
export interface MetricRows {
  groups: MetricGroup[];
  failures: { failed: number; total: number; rates: { level: string; slice: string; metric: string; value: number | null }[] };
  referenceCaveats: string[];
}

const sliceKey = (slice: Slice) => JSON.stringify(Object.entries(slice).sort(([a], [b]) => a.localeCompare(b)));
const sliceLabel = (slice: Slice) => Object.entries(slice).map(([key, value]) => `${key}: ${String(value)}`).join(", ") || "All items";
const valueOf = (entry: MetricEntry): MetricValue => ({
  value: entry.value, n: entry.n, clusters: entry.n_clusters,
  interval: entry.ci, intervalStatus: entry.ci_status,
});

/** Isolate the raw B3 report shape from rendering, preserving first-seen server order. */
export function toMetricRows(report: MetricsReport): MetricRows {
  const levels = new Map<string, Map<string, MetricGroup>>();
  for (const entry of report.entries) {
    if (entry.policy === "none") continue;
    let slices = levels.get(entry.level);
    if (!slices) { slices = new Map(); levels.set(entry.level, slices); }
    const key = sliceKey(entry.slice);
    let group = slices.get(key);
    if (!group) { group = { level: entry.level, slice: sliceLabel(entry.slice), rows: [] }; slices.set(key, group); }
    let row = group.rows.find(candidate => candidate.metric === entry.metric);
    if (!row) { row = { metric: entry.metric, references: [] }; group.rows.push(row); }
    row[entry.policy] = valueOf(entry);
  }
  for (const reference of report.references) {
    const group = levels.get(reference.level)?.get(sliceKey(reference.slice));
    group?.rows.find(row => row.metric === reference.metric)?.references.push({ value: reference.value, source: reference.source, label: reference.label, note: reference.note });
  }
  const rates = report.entries.filter(entry => entry.policy === "none").map(entry => ({
    level: entry.level, slice: sliceLabel(entry.slice), metric: entry.metric, value: entry.value,
  }));
  return {
    groups: [...levels.values()].flatMap(slices => [...slices.values()]),
    failures: { failed: report.items.failed, total: report.items.selected, rates },
    referenceCaveats: report.reference_caveats,
  };
}
