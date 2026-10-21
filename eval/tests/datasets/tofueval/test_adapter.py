"""Offline adapter integration uses fictional fixtures only."""

import json
import shutil
import socket
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from iaudit_eval import contracts
from iaudit_eval.datasets import DatasetError, load

FIXTURES = Path(__file__).with_name("fixtures")


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Adapter request assembly attempted network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    data = tmp_path / "tofueval"
    shutil.copytree(FIXTURES / "repo", data / "repo")
    with zipfile.ZipFile(FIXTURES / "mediasum/test_data.zip") as archive:
        media = [json.loads(line) for line in archive.read("test_data.txt").splitlines()]
    meetings = [json.loads(line) for line in (FIXTURES / "meetingbank/test.json").read_text().splitlines()]
    records = {f"mediasum:{r['id']}": r for r in media}
    records.update({f"meetingbank:{r['uid']}": r for r in meetings})
    (data / "derived").mkdir()
    (data / "derived/transcripts.json").write_text(json.dumps(records))
    return load("tofueval", data_root=tmp_path)


def test_discovery_load_is_lazy_without_local_data(tmp_path):
    dataset = load("tofueval", data_root=tmp_path)
    assert dataset.meta.name == "tofueval"
    assert not list(tmp_path.iterdir())
    with pytest.raises(DatasetError, match="split"):
        dataset.adapter.items("missing")


def test_all_fixture_requests_validate_without_network_and_transcripts_read_once(dataset, monkeypatch):
    started = time.perf_counter()
    items = dataset.items("all")
    assert len(items) == 5
    assert [i.id for i in dataset.adapter.items("all")] == [i.id for i in items]
    requests = [dataset.adapter.to_request(item) for item in items]
    assert all(not contracts.validate_request(request) for request in requests)
    assert all(set(request) == {"schema_version", "transcript", "assessment"} for request in requests)
    assert all(request["schema_version"] == contracts.schema_version() for request in requests)
    for item, request in zip(items, requests, strict=True):
        assert request["assessment"][0]["id"] == "s0"
        for sentence in item.payload["sentences"]:
            assert request["assessment"][0]["text"][sentence["start"]:sentence["end"]] == sentence["text"]
    # Both a new adapter instance and repeated requests share the process snapshot.
    (dataset.adapter.data_dir / "derived/transcripts.json").unlink()
    other = load("tofueval", data_root=dataset.adapter.data_dir.parent)
    requests[0]["transcript"][0]["text"] = "Caller mutation"
    assert other.adapter.to_request(items[0])["transcript"][0]["text"] != "Caller mutation"
    for item in items:
        assert not contracts.validate_request(dataset.adapter.to_request(item))
    elapsed = time.perf_counter() - started
    print(f"fixture assembly: {len(items)} items, {elapsed:.3f}s, network disabled")
    assert elapsed < 5


def test_invalid_request_raises_before_return(dataset):
    item = dataset.items("all")[0]
    broken = replace(item, payload={"sentences": []})
    with pytest.raises(DatasetError, match="request"):
        dataset.adapter.to_request(broken)


def test_refresh_invalidates_transcript_snapshot_and_items(dataset, monkeypatch):
    item = next(i for i in dataset.items("all") if i.meta["dataset"] == "meetingbank" and i.split == "dev")
    old = dataset.adapter.to_request(item)
    module = sys.modules[type(dataset.adapter).__module__]

    def offline_refresh(data_dir, progress):
        path = data_dir / "derived/transcripts.json"
        records = json.loads(path.read_text())
        records[f"{item.meta['dataset']}:{item.doc_id}"] = {"transcript": "Refreshed fictional evidence."}
        path.write_text(json.dumps(records))
        csv = data_dir / "repo/factual_consistency/meetingbank_factual_eval_dev.csv"
        csv.write_text(csv.read_text().replace("The fictional glasshouse has a clockwork orchard.", "A fictional garden grows."))
        return []

    monkeypatch.setattr(module.download_module, "download", offline_refresh)
    dataset.adapter.download(dataset.adapter.data_dir, None)
    assert dataset.adapter.to_request(item)["transcript"][0]["text"] == "Refreshed fictional evidence."
    assert dataset.adapter.to_request(item) != old
    refreshed = next(i for i in dataset.items("all") if i.id == item.id)
    assert refreshed.payload != item.payload


def test_failed_download_keeps_cached_snapshot(dataset, monkeypatch):
    item = dataset.items("all")[0]
    original = dataset.adapter.to_request(item)
    module = sys.modules[type(dataset.adapter).__module__]

    def failed_refresh(data_dir, progress):
        raise ValueError("Fictional failed download")

    monkeypatch.setattr(module.download_module, "download", failed_refresh)
    (dataset.adapter.data_dir / "derived/transcripts.json").unlink()
    with pytest.raises(ValueError, match="failed download"):
        dataset.adapter.download(dataset.adapter.data_dir, None)
    assert dataset.adapter.to_request(item) == original


def test_post_download_invalidates_destination_even_when_called_with_stage(dataset, tmp_path):
    item = dataset.items("all")[0]
    dataset.adapter.to_request(item)
    data_dir = dataset.adapter.data_dir
    path = data_dir / "derived/transcripts.json"
    records = json.loads(path.read_text())
    records[f"mediasum:{item.doc_id}"]["utt"][0] = "Fresh fictional utterance."
    path.write_text(json.dumps(records))
    dataset.adapter.post_download(tmp_path / "staging")
    assert dataset.adapter.to_request(item)["transcript"][0]["text"] == "Fresh fictional utterance."


def test_request_version_comes_from_loaded_schema(dataset, tmp_path, monkeypatch):
    contract_dir = tmp_path / "contracts"
    shutil.copytree(contracts.contracts_dir(), contract_dir)
    path = contract_dir / "audit-request.schema.json"
    schema = json.loads(path.read_text())
    schema["properties"]["schema_version"]["const"] = "9.0.0"
    path.write_text(json.dumps(schema))
    loaded = contracts.load_contracts(contract_dir)
    monkeypatch.setattr(contracts, "get_contracts", lambda: loaded)
    request = dataset.adapter.to_request(dataset.items("dev")[0])
    assert request["schema_version"] == "9.0.0"
    assert not contracts.validate_request(request)
