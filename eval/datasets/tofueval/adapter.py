"""Assemble validated audit requests from the local TofuEval snapshot."""

from pathlib import Path

from iaudit_eval import contracts
from iaudit_eval.datasets import DatasetError, Item

from . import download as download_module
from . import integrity, item_rows, labels, pairs, projection
from .assessment import build_assessment
from .items import load_items
from .mapping import FrozenMapping, load_mapping
from .transcripts import get_transcript_turns, invalidate_transcripts


class TofuEvalAdapter:
    def __init__(self, data_dir: Path):
        # Discovery and download must work before local data exists.
        self.data_dir = Path(data_dir)
        self._mapping: FrozenMapping | None = None

    def items(self, split: str) -> list[Item]:
        names = ("dev", "test")
        if split not in (*names, "all"):
            raise DatasetError(f"unknown split {split!r}; declared: {list(names)} (plus 'all')")
        items = load_items(self.data_dir / "repo")
        if split == "all":
            return [item for name in names for item in items if item.split == name]
        return [item for item in items if item.split == split]

    def to_request(self, item: Item) -> dict:
        section, _ = build_assessment(item.payload["sentences"])
        request = {
            "schema_version": contracts.schema_version(),
            "transcript": get_transcript_turns(self.data_dir, item.meta["dataset"], item.doc_id),
            "assessment": [section],
        }
        issues = contracts.validate_request(request)
        if issues:
            raise DatasetError("invalid TofuEval request: " + "; ".join(map(str, issues)))
        return request

    def download(self, data_dir: Path, progress):
        records = download_module.download(data_dir, progress)
        self.post_download(data_dir)
        return records

    def post_download(self, data_dir: Path):
        # The framework validates a staging directory before promoting it to
        # self.data_dir. Invalidate the destination snapshot as well as the stage.
        invalidate_transcripts(self.data_dir)
        invalidate_transcripts(data_dir)

    def _frozen_mapping(self) -> FrozenMapping:
        if self._mapping is None:
            self._mapping = load_mapping()
        return self._mapping

    def mapping_version(self) -> str:
        return self._frozen_mapping().mapping_version

    def gold(self, item: Item):
        return labels.gold(item)

    def check_request(self, request: dict, item: Item) -> bool:
        """True when the saved request's section-0 text equals the current local rebuild."""
        section, _ = build_assessment(item.payload["sentences"])
        try:
            saved = next(s for s in request["assessment"] if s.get("id") == section["id"])
        except (KeyError, TypeError, StopIteration):
            return False
        return saved.get("text") == section["text"]

    def project(self, response: dict, item: Item):
        return projection.project(response, item, self._frozen_mapping())

    def pairs(self, item: Item, gold, prediction, failure):
        return pairs.pairs(item, gold, prediction, failure, self._frozen_mapping())

    def item_row(self, item: Item, gold, prediction, failure):
        return item_rows.build(item, gold, prediction, failure, self._frozen_mapping())

    def report_extra(self, run: dict, runs_root: Path | None = None):
        return integrity.report_extra(run, runs_root, self._frozen_mapping())


def create(data_dir: Path) -> TofuEvalAdapter:
    return TofuEvalAdapter(data_dir)
