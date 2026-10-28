/** Hand mirrors of eval/api/eval-api.schema.json. Optional properties match required lists. */
export type ApiCode = "invalid_request" | "not_found" | "run_active" | "bad_state" | "data_missing" | "backend_unreachable" | "schema_mismatch" | "forbidden" | "internal_error";
export type EvalError =
  | { kind: "unreachable" }
  | { kind: "timeout"; seconds: number }
  | { kind: "cancelled" }
  | { kind: "api"; status: number; code: ApiCode; message: string; detail?: unknown }
  | { kind: "bad_body"; message: string };
export interface CallOpts { signal?: AbortSignal }
export interface ErrorResponse { error: { code: ApiCode; message: string; detail?: unknown } }
export interface BackendHealth { url: string; reachable: boolean; schema_version?: string | null }
export interface Health { status?: "ok"; eval_api_version: string; backend: BackendHealth }
export interface SplitSummary { name: string; size: number | null }
export interface SplitMeta extends SplitSummary { description?: string }
export interface DatasetSummary { name: string; product: string; title: string; data_present: boolean; splits: SplitSummary[] }
export interface DatasetMeta {
  [key: string]: unknown;
  name: string; product: string; splits: SplitMeta[]; title?: string; kind?: string; description?: string;
  dataset_version?: string; default_split?: string; test_split_note?: string | null;
  data_required?: boolean; cluster_key?: string; pool_all?: boolean; gold_kind?: string | null;
  mapping?: string | null; references?: string | null; levels?: Record<string, unknown>;
  license?: Record<string, unknown>; sources?: Record<string, unknown>[];
  slices?: string[]; metrics?: Record<string, unknown>[] | null;
}
export interface DownloadFile { id: string; filename: string; sha256: string; size_bytes: number; fetched_at: string }
export interface DownloadStatus { status: "not_downloaded" | "downloading" | "ready" | "failed"; files?: DownloadFile[]; warnings?: string[]; error?: string | null; updated_at?: string | null }
export interface EstimateRequest { dataset: string; split: string; n?: number | null; seed?: number | null }
export interface RunRequest extends EstimateRequest { max_cost_usd?: number | null; tags?: Record<string, unknown> | null }
export interface Estimate { basis: "prior_runs" | "none"; n_items: number; est_input_tokens: number | null; est_output_tokens: number | null; est_cost_usd: number | null; rough: true; note: string }
export interface RunCreated { run_id: string }
export type RunState = "running" | "finished" | "aborted" | "aborted_cost" | "interrupted" | "failed";
export type ScoreState = "pending" | "running" | "done" | "failed";
export interface RunTotals { cost_usd: number | null; failures: number }
export interface Progress { done: number; total: number; failures: number; cost_usd: number | null }
export interface RunSummary {
  run_id: string; dataset: string; split: string; n_requested: number | null; n_items: number;
  seed: number | null; created_at: string; finished_at?: string | null; schema_version: string | null;
  state: RunState; score_state: ScoreState; totals: RunTotals; git_dirty: boolean | null;
}
export interface RunInfo {
  concurrency: number; fingerprint?: Record<string, unknown> | null; git_commit?: string | null;
  git_dirty?: boolean | null; mapping_version?: string | null; max_cost_usd?: number | null;
  mixed?: boolean; seed?: number | null; tags?: Record<string, unknown>; warnings?: string[];
}
export interface RunError { [key: string]: unknown; kind: string; message: string }
export interface ResumeRefusal { kind: "fingerprint_changed" | "schema_version_changed"; changes: { field: string; was?: unknown; now?: unknown }[] }
export interface ResumeRequest { max_cost_usd?: number | null }
export interface RunDetail extends RunSummary { progress: Progress; run_info: RunInfo; error?: RunError | null; resume_refusal?: ResumeRefusal | null }
export type ItemStatus = "ok" | "failed" | "unmapped";
export type ItemFilter = "all" | "mismatch" | "failed";
export interface ItemQuery { filter?: ItemFilter; limit?: number; offset?: number }
export interface ItemRow { item_id: string; status: ItemStatus; gold: string | null; pred: string | null; match: boolean | null; label?: string; outcome?: string; detail?: Record<string, unknown> }
export interface ItemPage { total: number; items: ItemRow[] }
export interface ItemDetail {
  item_id: string; status: ItemStatus; request: Record<string, unknown>; response: Record<string, unknown> | null;
  failure: Record<string, unknown> | null; run_info: Record<string, unknown> | null; gold: unknown; gold_kind: string | null;
}
export type Slice = Record<string, string | number | boolean | null>;
export type ConfidenceInterval = [number, number] | null;
export type CiStatus = "ok" | "few_clusters" | "undefined";
export type Policy = "primary" | "secondary" | "none";
export interface MetricEntry {
  metric: string; level: string; policy: Policy; slice: Slice; value: number | null; n: number;
  n_clusters: number; ci: ConfidenceInterval; ci_status: CiStatus; impl?: string;
}
export interface MetricReference { source: string; label: string; metric: string; level: string; slice: Slice; value: number; note?: string }
export interface MetricsReport {
  schema_version: "1.0.0"; run_id: string; dataset: string; dataset_version: string; primary_policy: string;
  scored: { at: string; metrics_version: string; git_commit: string; git_dirty: boolean };
  bootstrap: { method: string; resamples: number; seed: number; level: number };
  run: { state: RunState; complete: boolean; mapping_version: string | null; tags: Record<string, unknown> };
  dataset_extra: Record<string, unknown>; reference_caveats: string[];
  items: { selected: number; scored: number; failed: number; not_run: number };
  failures: { by_reason: Record<string, number> }; entries: MetricEntry[]; references: MetricReference[];
}
export interface ComparisonSide { value: number | null; n: number; ci: ConfidenceInterval }
export interface ComparisonDelta {
  metric: string; level: string; policy: Policy; slice: Slice; a: ComparisonSide; b: ComparisonSide;
  delta: number | null; delta_ci: ConfidenceInterval; ci_status: CiStatus; n_clusters: number;
}
export interface Disagreement { item_id: string; cluster: string; pairs: { level: string; unit: string; gold: string; a: string | null; b: string | null }[] }
export interface Comparison {
  schema_version: "1.0.0"; run_a: string; run_b: string; dataset: string; warnings: string[];
  n_shared: number; n_a_only: number; n_b_only: number; n_clusters_shared: number;
  deltas: ComparisonDelta[]; disagreements: Disagreement[];
}
