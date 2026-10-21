"""Assemble validated audit requests from the local TofuEval snapshot."""

from pathlib import Path

from iaudit_eval import contracts
from iaudit_eval.datasets import DatasetError, Item

from . import download as download_module
from .assessment import build_assessment
from .items import load_items
from .transcripts import get_transcript_turns, invalidate_transcripts


class TofuEvalAdapter:
    def __init__(self, data_dir: Path):
        # Discovery and download must work before local data exists.
        self.data_dir = Path(data_dir)

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

    def gold(self, item: Item):
        raise NotImplementedError("TofuEval gold projection is implemented by C2")

    def project(self, response: dict, item: Item):
        raise NotImplementedError("TofuEval response projection is implemented by C2")


def create(data_dir: Path) -> TofuEvalAdapter:
    return TofuEvalAdapter(data_dir)
