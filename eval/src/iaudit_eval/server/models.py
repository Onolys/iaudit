"""Eval HTTP contracts; B2/B3 remain the sources for stored data and report shapes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, with_config

from iaudit_eval.metrics.report import ItemRow as ScoredItemRow

RunState = Literal["running", "finished", "aborted", "aborted_cost", "interrupted", "failed"]
ScoreState = Literal["pending", "running", "done", "failed"]
DownloadState = Literal["not_downloaded", "downloading", "ready", "failed"]
ItemStatus = Literal["ok", "failed", "unmapped"]
ItemFilter = Literal["all", "mismatch", "failed"]
ErrorCode = Literal[
    "invalid_request", "not_found", "run_active", "bad_state", "data_missing",
    "backend_unreachable", "schema_mismatch", "forbidden", "internal_error",
]
DatasetName = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
NonnegativeInt = Annotated[int, Field(ge=0)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BackendHealth(Model):
    url: str
    reachable: bool
    schema_version: str | None = None


class Health(Model):
    status: Literal["ok"] = "ok"
    eval_api_version: str
    backend: BackendHealth


class SplitSummary(Model):
    name: str
    size: NonnegativeInt | None


class SplitMeta(SplitSummary):
    description: str = ""


class DatasetSummary(Model):
    name: str
    title: str
    data_present: bool
    splits: list[SplitSummary]


class DatasetMeta(Model):
    # Unknown metadata fields are preserved, just as by B2 DatasetMeta.to_dict().
    model_config = ConfigDict(extra="allow")
    name: str
    title: str = ""
    description: str = ""
    dataset_version: str = ""
    kind: str = "adapter"
    splits: list[SplitMeta]
    default_split: str = ""
    cluster_key: str = ""
    license: dict[str, Any] = Field(default_factory=dict)
    data_required: bool = False
    sources: list[dict[str, Any]] = Field(default_factory=list)
    test_split_note: str | None = None
    slices: list[str] = Field(default_factory=list)
    mapping: str | None = None
    references: str | None = None
    levels: dict[str, Any] = Field(default_factory=dict)
    metrics: list[dict[str, Any]] | None = None
    pool_all: bool = True
    gold_kind: str | None = None


class DownloadFile(Model):
    id: str
    filename: str
    sha256: str
    size_bytes: NonnegativeInt
    fetched_at: str


class DownloadStatus(Model):
    status: DownloadState
    error: str | None = None
    files: list[DownloadFile] = Field(default_factory=list)
    updated_at: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EstimateRequest(Model):
    dataset: DatasetName
    split: Annotated[str, Field(min_length=1)]
    n: Annotated[int, Field(ge=1)] | None = None
    seed: int | None = None


class RunRequest(EstimateRequest):
    max_cost_usd: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    tags: dict[str, Any] | None = None


class Estimate(Model):
    """B2 Estimate, without field renames, invented figures, or extra fields."""

    basis: Literal["prior_runs", "none"]
    n_items: NonnegativeInt
    est_input_tokens: float | None
    est_output_tokens: float | None
    est_cost_usd: float | None
    rough: Literal[True]
    note: str


class RunCreated(Model):
    run_id: str


class RunTotals(Model):
    cost_usd: float | None
    failures: NonnegativeInt


class RunSummary(Model):
    run_id: str
    dataset: str
    split: str
    n_requested: NonnegativeInt | None
    n_items: NonnegativeInt
    seed: int | None
    created_at: str
    finished_at: str | None = None
    schema_version: str | None
    state: RunState
    score_state: ScoreState
    totals: RunTotals
    git_dirty: bool | None


class Progress(Model):
    done: NonnegativeInt
    total: NonnegativeInt
    failures: NonnegativeInt
    cost_usd: float | None


class RunInfo(Model):
    git_commit: str | None = None
    git_dirty: bool | None = None
    fingerprint: dict[str, Any] | None = None
    mapping_version: str | None = None
    seed: int | None = None
    concurrency: Annotated[int, Field(ge=1)]
    max_cost_usd: float | None = None
    tags: dict[str, Any] = Field(default_factory=dict)
    mixed: bool = False
    warnings: list[str] = Field(default_factory=list)


class RunError(Model):
    """Engine failure with its kind/message and unmodified diagnostic fields."""

    model_config = ConfigDict(extra="allow")
    kind: str
    message: str


class RunDetail(RunSummary):
    progress: Progress
    run_info: RunInfo
    error: RunError | None = None


@with_config(ConfigDict(extra="forbid"))
class ItemRow(ScoredItemRow):
    """B3 row, widened only for pre-score gold=null per the HTTP contract."""

    gold: str | None


class ItemPage(Model):
    total: NonnegativeInt
    items: list[ItemRow]


class ItemDetail(Model):
    item_id: str
    status: ItemStatus
    request: dict[str, Any]
    response: dict[str, Any] | None
    failure: dict[str, Any] | None
    run_info: dict[str, Any] | None
    gold: Any
    gold_kind: str | None


class Error(Model):
    code: ErrorCode
    message: str
    detail: Any = None


class ErrorResponse(Model):
    error: Error
