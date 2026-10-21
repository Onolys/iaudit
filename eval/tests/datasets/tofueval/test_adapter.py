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


def _saved_run(root, run_id, *, split="test", version="1.0.0", **fields):
    from iaudit_eval import store

    store.create_run(root, {
        "run_id": run_id, "dataset": "tofueval", "split": split,
        "mapping_version": version, "item_ids": [],
        "created_at": "2026-10-20T10:00:00+00:00", **fields,
    })
    return store.load_run(root, run_id)


def test_integrity_counts_matching_runs_read_only_in_chronological_order(dataset, tmp_path):
    from iaudit_eval import store

    root = tmp_path / "runs"
    current = _saved_run(root, "b-current", split="all")
    _saved_run(root, "a-same-time")
    _saved_run(root, "z-earlier", created_at="2026-10-20T10:30:00+01:00")
    _saved_run(root, "c-later", created_at="2026-10-20T12:00:00Z")
    for run_id, state in [("running", "running"), ("finished", "finished"),
                          ("aborted-cost", "aborted_cost"), ("aborted", "aborted"),
                          ("failed", "failed")]:
        _saved_run(root, run_id)
        store.update_run(root, run_id, state=state)
    dev = _saved_run(root, "dev", split="dev")
    _saved_run(root, "other-version", version="2.0.0")
    _saved_run(root, "other-dataset", dataset="synthetic")
    _saved_run(root, "invalid-split", split="other")
    _saved_run(root, "invalid-date", created_at="not-a-date")
    _saved_run(root, "naive-date", created_at="2026-10-20T10:00:00")
    _saved_run(root, "invalid-id")
    path = root / "invalid-id/run.json"
    raw = json.loads(path.read_text())
    raw["run_id"] = "different-folder"
    path.write_text(json.dumps(raw))
    for name, body in [("broken", "{"), ("array", "[]"), ("scalar", "null"),
                       ("incomplete", '{"dataset":"tofueval"}')]:
        folder = root / name
        folder.mkdir()
        (folder / "run.json").write_text(body)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}
    extra = dataset.adapter.report_extra(current, root)
    assert extra["mapping_version"] == "1.0.0"
    assert len(extra["mapping_sha256"]) == 64
    assert extra["test_run_count"] == 9
    assert extra["test_run_ordinal"] == 5  # z-earlier, a, aborted, aborted-cost, current
    assert extra["dev_run_count"] == 1
    assert "0.34" in extra["label_noise_note"] and "0.42" in extra["label_noise_note"]
    assert "exclud" in extra["secondary_excludes_failures"].lower()
    assert extra["primary_policy"] == "failures_count_wrong"
    assert dataset.adapter.report_extra(dev, root)["test_run_ordinal"] is None
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def test_integrity_default_root_and_missing_root(dataset, tmp_path, monkeypatch):
    monkeypatch.setenv("IAUDIT_EVAL_HOME", str(tmp_path / "home"))
    run = _saved_run(tmp_path / "home/runs", "current")
    assert dataset.adapter.report_extra(run)["test_run_count"] == 1
    empty = dataset.adapter.report_extra(run, tmp_path / "absent")
    assert empty["test_run_count"] == 0
    assert empty["test_run_ordinal"] is None
    assert not (tmp_path / "absent").exists()


def test_mapping_is_lazy_cached_and_independent_of_downloaded_data(tmp_path, monkeypatch):
    dataset = load("tofueval", data_root=tmp_path)
    original = Path.read_bytes
    reads = []

    def counted(path):
        if path.name == "mapping.json":
            reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    assert reads == []
    assert dataset.adapter.mapping_version() == "1.0.0"
    assert dataset.adapter.mapping_version() == "1.0.0"
    assert not list(tmp_path.iterdir())
    assert len(reads) == 1


def test_saved_fixture_scoring_uses_adapter_hooks_and_compare_warns(dataset, tmp_path, monkeypatch):
    from iaudit_eval import store
    from iaudit_eval.compare import compare
    from iaudit_eval.scoring import score

    root = tmp_path / "runs"
    items = dataset.items("test")
    item = items[0]
    sentence = item.payload["sentences"][0]
    response = {
        "schema_version": "1.1.0", "status": "complete", "warnings": [],
        "claims": [{"id": "fictional", "verdict": "supported", "concerns": [],
                    "explanation": "Fictional support.",
                    "evidence": [{"id": "e1", "role": "supporting",
                                  "span": {"start": {"index": 0, "char": 0},
                                           "end": {"index": 0, "char": 1}}}],
                    "span": {"start": {"index": 0, "char": sentence["start"]},
                             "end": {"index": 0, "char": sentence["end"]}}}],
    }
    assert not contracts.validate_response(response)
    original = Path.read_bytes
    mapping_reads = []

    def counted(path):
        if path.name == "mapping.json":
            mapping_reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    gold = dataset.adapter.gold(item)
    prediction = dataset.adapter.project(response, item)
    assert gold["sentences"][0]["label"] in {"consistent", "inconsistent"}
    assert prediction["sentences"][0]["label"] == "consistent"
    assert dataset.adapter.pairs(item, gold, prediction, None)
    assert dataset.adapter.item_row(item, gold, prediction, None)["item_id"] == item.id
    for _ in range(3):
        dataset.adapter.project(response, item)
        dataset.adapter.pairs(item, gold, prediction, None)
        dataset.adapter.item_row(item, gold, prediction, None)
        dataset.adapter.report_extra({"split": "dev"}, root)
    assert len(mapping_reads) == 1
    failed = dataset.adapter.item_row(item, gold, None, "item_failed")
    assert failed["outcome"] == "unresolved"
    assert all(p.failure == "unresolved" for p in dataset.adapter.pairs(item, gold, None, "item_failed")
               if p.level in {"sentence", "summary"})
    for run_id, version in [("first", dataset.adapter.mapping_version()), ("second", "2.0.0")]:
        _saved_run(root, run_id, version=version, item_ids=[item.id])
        store.write_item(root, run_id, {"item_id": item.id, "status": "ok", "response": response})
        store.update_run(root, run_id, state="finished")
    report = score("first", runs_root=root, data_root=dataset.adapter.data_dir.parent)
    assert report["dataset_extra"]["test_run_count"] == 1
    assert report["dataset_extra"]["test_run_ordinal"] == 1
    assert report["run"]["mapping_version"] == "1.0.0"
    assert report["entries"]
    persisted = json.loads((root / "first/item_rows.json").read_text())
    assert persisted["rows"][0]["item_id"] == item.id
    assert '"text"' not in json.dumps(persisted)
    assert '"exp"' not in json.dumps(persisted)
    result = compare("first", "second", runs_root=root, data_root=dataset.adapter.data_dir.parent)
    assert any("mapping_version differs" in warning for warning in result["warnings"])
    assert result["n_shared"] == 1
