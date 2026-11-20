// Hand-written types for the paudit result. `RESULT_KEYS` lists every property and the required
// ones per type; each list is compile-checked against the type and runtime-checked against
// engines/paudit/schemas/paudit-result.schema.json by pauditSchema.test.ts.

export type Label = "below_fair" | "fair" | "good";
export interface Reference { fair: number; good: number }
export interface Stat { mean: number; min: number; max: number; values: number[] }
export interface SummaryStat {
  mean: number | null; min: number | null; max: number | null; values: (number | null)[];
  label?: Label | null; reference?: Reference | null;
}
export interface Summary { value: number | null; label: Label | null; reference: Reference | null }
export interface Evidence { turn_id: string; start: number; end: number; quote: string }
export interface GlobalScore {
  score: number; source: "model" | "default" | "capped"; raw_score: number; reason: string; evidence: Evidence[];
}
export interface Instance {
  id: string; volley_id: string; turn_id: string; start: number; end: number;
  start_ms?: number | null; end_ms?: number | null;
  quote: string; code: string | null; counted: boolean; uncounted_reason?: string | null; rationale: string;
}
export interface ResultWarning {
  code: string; severity?: "info" | "warning"; item_id?: string | null; detail?: string | null;
}
export interface RunResult {
  run_index: number; instances: Instance[]; counts: Record<string, number>;
  globals: Record<string, GlobalScore>; summaries: Record<string, Summary>; warnings: ResultWarning[];
}
export interface Aggregate {
  counts: Record<string, Stat>; globals: Record<string, Stat>; summaries: Record<string, SummaryStat>;
  representative_run: number;
}
export interface CodedSpan { from_s?: number | null; to_s?: number | null }
export interface ProtocolBlock { id: string; version: string; pack_hash: string; pack_format: string }
export interface PackFacts { id: string; version: string; hash: string }
export interface RouteFacts {
  litellm_id: string; provider: string; structured_output_mode: "json_object" | "json_schema";
  temperature_effective: number | null; params_hash: string;
}
export interface SttRun {
  provider: string; model: string; location?: string | null; language_requested: string;
  language_detected?: string | null; adapter_version: string;
}
export interface RunUsage {
  calls?: number; input_tokens?: number; output_tokens?: number; cache_read_tokens?: number;
  cache_write_tokens?: number; cost_usd?: number | null;
}
export interface RunInfo {
  engine: string; code_version: string; preset?: string | null; routes?: Record<string, RouteFacts>;
  stt?: SttRun | null; pack?: PackFacts | null; prompt_hashes?: Record<string, string>;
  n_runs?: number; usage?: RunUsage;
}
export interface PauditResult {
  schema_version: "0.0.1"; request_id?: string | null; protocol: ProtocolBlock; language: string;
  change_goal?: string | null; coded_span?: CodedSpan | null; subject_speaker: string; n_runs: number;
  results: RunResult[]; aggregate: Aggregate; warnings: ResultWarning[]; run_info: RunInfo;
}

// --- request side (POST /v1/paudit) and fixtures ---
export interface TranscriptTurn { id: string; speaker: string; text: string; start_ms?: number | null; end_ms?: number | null }
export interface PauditTranscript { turns: TranscriptTurn[]; language?: string; [key: string]: unknown }
export interface PauditParams {
  speaker_map: { subject: string; [role: string]: string };
  change_goal: string;
  coded_span?: { from_s: number; to_s: number };
  language?: string;
  n_runs?: number;
}
export interface PauditRequest { transcript: PauditTranscript; pack: string; params: PauditParams; request_id?: string }
export interface FixtureSummary { name: string; description: string; pack: string; turns: number; params: PauditParams }
export interface Fixture { name: string; description: string; pack: string; transcript: PauditTranscript; params: PauditParams }

type Keys<T> = { all: readonly (keyof T & string)[]; required: readonly (keyof T & string)[] };
// Compile-time: `all` must be exactly the keys of T (no missing, no extra) via the mapped record.
function keys<T>(all: Record<keyof T, true>, required: readonly (keyof T & string)[]): Keys<T> {
  return { all: Object.keys(all) as (keyof T & string)[], required };
}

export const RESULT_KEYS = {
  PauditResult: keys<PauditResult>(
    { schema_version: true, request_id: true, protocol: true, language: true, change_goal: true, coded_span: true,
      subject_speaker: true, n_runs: true, results: true, aggregate: true, warnings: true, run_info: true },
    ["schema_version", "protocol", "language", "subject_speaker", "n_runs", "results", "aggregate", "warnings", "run_info"]),
  Aggregate: keys<Aggregate>({ counts: true, globals: true, summaries: true, representative_run: true },
    ["counts", "globals", "summaries", "representative_run"]),
  CodedSpan: keys<CodedSpan>({ from_s: true, to_s: true }, []),
  Evidence: keys<Evidence>({ turn_id: true, start: true, end: true, quote: true }, ["turn_id", "start", "end", "quote"]),
  GlobalScore: keys<GlobalScore>({ score: true, source: true, raw_score: true, reason: true, evidence: true },
    ["score", "source", "raw_score", "reason", "evidence"]),
  Instance: keys<Instance>(
    { id: true, volley_id: true, turn_id: true, start: true, end: true, start_ms: true, end_ms: true, quote: true,
      code: true, counted: true, uncounted_reason: true, rationale: true },
    ["id", "volley_id", "turn_id", "start", "end", "quote", "code", "counted", "rationale"]),
  PackFacts: keys<PackFacts>({ id: true, version: true, hash: true }, ["id", "version", "hash"]),
  ProtocolBlock: keys<ProtocolBlock>({ id: true, version: true, pack_hash: true, pack_format: true },
    ["id", "version", "pack_hash", "pack_format"]),
  Reference: keys<Reference>({ fair: true, good: true }, ["fair", "good"]),
  ResultWarning: keys<ResultWarning>({ code: true, severity: true, item_id: true, detail: true }, ["code"]),
  RouteFacts: keys<RouteFacts>(
    { litellm_id: true, provider: true, structured_output_mode: true, temperature_effective: true, params_hash: true },
    ["litellm_id", "provider", "structured_output_mode", "temperature_effective", "params_hash"]),
  RunInfo: keys<RunInfo>(
    { engine: true, code_version: true, preset: true, routes: true, stt: true, pack: true, prompt_hashes: true,
      n_runs: true, usage: true },
    ["engine", "code_version"]),
  RunResult: keys<RunResult>(
    { run_index: true, instances: true, counts: true, globals: true, summaries: true, warnings: true },
    ["run_index", "instances", "counts", "globals", "summaries", "warnings"]),
  RunUsage: keys<RunUsage>(
    { calls: true, input_tokens: true, output_tokens: true, cache_read_tokens: true, cache_write_tokens: true, cost_usd: true }, []),
  Stat: keys<Stat>({ mean: true, min: true, max: true, values: true }, ["mean", "min", "max", "values"]),
  SttRun: keys<SttRun>(
    { provider: true, model: true, location: true, language_requested: true, language_detected: true, adapter_version: true },
    ["provider", "model", "language_requested", "adapter_version"]),
  Summary: keys<Summary>({ value: true, label: true, reference: true }, ["value", "label", "reference"]),
  SummaryStat: keys<SummaryStat>({ mean: true, min: true, max: true, values: true, label: true, reference: true },
    ["mean", "min", "max", "values"]),
} as const;
