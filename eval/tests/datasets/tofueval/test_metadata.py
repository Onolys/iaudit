"""Offline contract for metadata consumed by dataset discovery and the Download UI."""

from pathlib import Path

from iaudit_eval.datasets import list_datasets

DATASETS = Path(__file__).resolve().parents[3] / "datasets"


def test_tofueval_metadata_is_discoverable_without_local_data():
    meta = {entry.name: entry for entry in list_datasets(DATASETS)}["tofueval"]

    assert meta.title == "TofuEval"
    assert meta.description
    assert meta.dataset_version == "17555c5bfc27f95371fd82b2de7014d8e14e1024"
    assert meta.kind == "adapter"
    assert meta.split_names() == ["dev", "test"]
    assert all(split["description"] for split in meta.splits)
    assert meta.default_split == "dev"
    assert meta.cluster_key == "source document"
    assert meta.data_required is True
    assert meta.license["redistributable"] is False
    assert meta.license["contains_licensed_text"] is True
    assert meta.test_split_note

    exposed = meta.to_dict()
    assert exposed["adapter_version"] == "1.0.0"
    assert exposed["item_unit"] == "summary"
    assert exposed["expected_sha256"] == {}
    assert meta.get("expected_sha256") == {}

    sources = {source["id"]: source for source in meta.sources}
    assert set(sources) == {"tofueval", "mediasum", "meetingbank"}
    assert sources["tofueval"]["revision"] == "17555c5bfc27f95371fd82b2de7014d8e14e1024"
    assert sources["tofueval"]["license"] == "MIT-0 (no-training note)"
    assert sources["mediasum"]["license"] == "research use"
    assert sources["meetingbank"]["license"] == "CC BY-NC-ND 4.0"
    for name in ("mediasum", "meetingbank"):
        assert sources[name]["revision"] == "resolve-at-first-download"
    for source in sources.values():
        assert source["url"].startswith("https://")
        # The framework validates even custom-hook sources as single safe filenames.
        assert "/" not in source["filename"]
        assert ".." not in source["filename"]
