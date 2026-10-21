"""All network bytes are fictional local fixtures via an injected transport."""

import importlib.util
import io
import json
import sys
import zipfile
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from iaudit_eval import download as framework
from iaudit_eval.datasets.base import Dataset, DatasetMeta

FIXTURES = Path(__file__).with_name("fixtures")
MODULE = Path(__file__).resolve().parents[3] / "datasets/tofueval/download.py"


def hook():
    assert MODULE.is_file(), "Download hook is not implemented"
    spec = importlib.util.spec_from_file_location(
        "fictional_download", MODULE, submodule_search_locations=[str(MODULE.parent)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def network():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for path in sorted((FIXTURES / "repo").rglob("*")):
            if path.is_file():
                z.writestr(
                    "tofueval-revision/" + path.relative_to(FIXTURES / "repo").as_posix(),
                    path.read_bytes(),
                )
        z.writestr("tofueval-revision/completeness/ignored.csv", "ignored")
        z.writestr("tofueval-revision/LICENSE", "Fictional fixture license")
    bodies = {
        "tofueval.zip": archive.getvalue(),
        "test_data.zip": (FIXTURES / "mediasum/test_data.zip").read_bytes(),
        "test.json": (FIXTURES / "meetingbank/test.json").read_bytes(),
    }
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if "/api/datasets/" in request.url.path:
            return httpx.Response(200, json={"sha": "a" * 40})
        return httpx.Response(
            200,
            content=bodies[
                "tofueval.zip"
                if request.url.host == "github.com"
                else request.url.path.rsplit("/", 1)[-1]
            ],
        )

    metadata = json.loads((MODULE.parent / "metadata.json").read_text())
    return metadata, bodies, calls, httpx.MockTransport(respond)


def fetch(tmp_path, network):
    metadata, _, _, transport = network
    return hook().download(tmp_path / "tofueval", None, metadata=metadata, transport=transport)


def test_fetch_records_all_files_resolves_ids_and_pins_hf(tmp_path, network):
    records = fetch(tmp_path, network)
    root = tmp_path / "tofueval"
    assert (root / "mediasum/test_data.zip").read_bytes() == network[1]["test_data.zip"]
    assert not list(root.rglob("completeness"))
    derived = (root / "derived/transcripts.json").read_bytes()
    assert len(json.loads(derived)) == 4
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["id_resolution"] == {
        "mediasum": {"wanted": 2, "resolved": 2},
        "meetingbank": {"wanted": 2, "resolved": 2},
    }
    assert len(manifest["duplicates"]) == 1
    assert all(
        "/resolve/" + "a" * 40 + "/" in s["url"]
        for s in manifest["sources"]
        if s["id"] != "tofueval"
    )
    assert {r.filename for r in records} == {
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
    }
    for record in records:
        assert record.sha256 == sha256((root / record.filename).read_bytes()).hexdigest()
    network[2].clear()
    fetch(tmp_path, network)
    assert not any("/api/datasets/" in url for url in network[2])
    assert (root / "derived/transcripts.json").read_bytes() == derived


@pytest.mark.parametrize("change", ["missing", "duplicate", "ambiguous", "invalid_turns", "hash"])
def test_failure_publishes_no_partial_data(tmp_path, network, change):
    metadata, bodies, _, _ = network
    rows = [json.loads(line) for line in bodies["test.json"].splitlines()]
    bad_id = rows[0]["uid"]
    if change == "missing":
        rows.pop(0)
    elif change == "duplicate":
        rows.append(rows[0])
    elif change == "ambiguous":
        rows.append(dict(rows[0], transcript="Different fictional evidence."))
    elif change == "invalid_turns":
        rows[0]["transcript"] = ""
    else:
        metadata["expected_sha256"] = {"repo/document_ids_dev_test_split.json": "0" * 64}
    bodies["test.json"] = b"\n".join(json.dumps(row).encode() for row in rows)
    with pytest.raises(
        (ValueError, AssertionError), match="sha256" if change == "hash" else bad_id
    ):
        fetch(tmp_path, network)
    assert not (tmp_path / "tofueval").exists()
    assert not list(tmp_path.glob(".tofueval-*"))


def test_failed_refresh_preserves_good_dataset(tmp_path, network):
    fetch(tmp_path, network)
    root = tmp_path / "tofueval"
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    network[0]["expected_sha256"] = {"meetingbank/test.json": "0" * 64}
    with pytest.raises(ValueError, match="sha256"):
        fetch(tmp_path, network)
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_framework_nested_records_noop_tamper_and_failed_refresh(tmp_path, network):
    module = hook()
    metadata = network[0]
    adapter = SimpleNamespace(
        download=lambda d, p: module.download(d, p, metadata=metadata, transport=network[3])
    )
    meta = DatasetMeta(
        name="tofueval", sources=tuple(metadata["sources"]), extra={"expected_sha256": {}}
    )
    ds = Dataset(meta, adapter)
    first = framework.download(ds, data_root=tmp_path)
    assert first["status"] == "ready"
    network[2].clear()
    assert framework.hash_warnings(ds, data_root=tmp_path) == []
    assert framework.download(ds, data_root=tmp_path) == first
    assert network[2] == []
    (tmp_path / "tofueval/derived/transcripts.json").write_text("{}")
    assert any(
        "derived/transcripts.json" in w for w in framework.hash_warnings(ds, data_root=tmp_path)
    )
    assert framework.download(ds, data_root=tmp_path)["status"] == "ready"
    assert network[2]
    metadata["expected_sha256"] = {"meetingbank/test.json": "0" * 64}
    ds = replace(ds, meta=replace(meta, extra={"expected_sha256": metadata["expected_sha256"]}))
    result = framework.download(ds, data_root=tmp_path)
    assert result["status"] == "failed"
    assert framework.status(ds, data_root=tmp_path)["status"] == "failed"
    assert "sha256" in framework.status(ds, data_root=tmp_path)["error"]


def test_pinned_extracted_file_accepts_repacked_archive_and_reports_progress(tmp_path, network):
    network[0]["expected_sha256"] = {
        "repo/document_ids_dev_test_split.json": sha256(
            (FIXTURES / "repo/document_ids_dev_test_split.json").read_bytes()
        ).hexdigest()
    }
    progress = []
    module = hook()
    first = module.download(
        tmp_path / "tofueval",
        lambda *args: progress.append(args),
        metadata=network[0],
        transport=network[3],
    )
    assert len(progress) >= 3
    assert all(done > 0 and (total is None or done <= total) for _, done, total in progress)
    # The annotation bytes remain identical when upstream archive metadata changes.
    archive = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(network[1]["tofueval.zip"])) as old,
        zipfile.ZipFile(archive, "w") as new,
    ):
        new.comment = b"fictional repack"
        for member in old.infolist():
            new.writestr(member, old.read(member))
    network[1]["tofueval.zip"] = archive.getvalue()
    second = fetch(tmp_path, network)
    a, b = ({r.filename: r.sha256 for r in records} for records in (first, second))
    assert a["raw/tofueval.zip"] != b["raw/tofueval.zip"]
    assert a["derived/transcripts.json"] == b["derived/transcripts.json"]


def test_directory_promotion_failure_restores_previous_snapshot(tmp_path, network, monkeypatch):
    module = hook()
    target = tmp_path / "tofueval"
    module.download(target, None, metadata=network[0], transport=network[3])
    before = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    original = module.os.replace

    def fail_promotion(source, destination):
        if Path(destination) == target and not str(source).endswith("-backup"):
            raise OSError("fictional rename failure")
        return original(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_promotion)
    with pytest.raises(OSError, match="fictional rename failure"):
        module.download(target, None, metadata=network[0], transport=network[3])
    assert {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    } == before
    assert not list(tmp_path.glob(".tofueval-*"))


@pytest.mark.parametrize(
    "name",
    ["../outside", "/absolute", "./child", "a/../child", "a//child", "a\\child", "linked/child"],
)
def test_framework_rejects_unsafe_custom_record_paths(tmp_path, name):
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    (outside / "child").write_bytes(b"fictional")

    def unsafe(data_dir, progress):
        (data_dir / "linked").symlink_to(outside, target_is_directory=True)
        return [
            framework.FileRecord("unsafe", name, sha256(b"fictional").hexdigest(), 9, "fixture")
        ]

    ds = Dataset(DatasetMeta(name="unsafe", sources=()), SimpleNamespace(download=unsafe))
    result = framework.download(ds, data_root=tmp_path)
    assert result["status"] == "failed"
    assert "invalid download record" in result["error"]


def test_framework_post_hook_failure_preserves_previous_dataset(tmp_path, network):
    module = hook()
    adapter = SimpleNamespace(
        download=lambda d, p: module.download(d, p, metadata=network[0], transport=network[3])
    )
    ds = Dataset(DatasetMeta(name="tofueval", sources=tuple(network[0]["sources"])), adapter)
    assert framework.download(ds, data_root=tmp_path)["status"] == "ready"
    root = tmp_path / "tofueval"
    (root / "derived/transcripts.json").write_text("fictional stale cache")
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def reject(_data_dir):
        raise ValueError("fictional post validation failure")

    adapter.post_download = reject
    result = framework.download(ds, data_root=tmp_path)
    assert result["status"] == "failed"
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    before.pop(Path("download.json"))
    after.pop(Path("download.json"))
    assert after == before
    saved = framework.status(ds, data_root=tmp_path)
    assert saved["status"] == "failed"
    assert "fictional post validation failure" in saved["error"]


def test_normal_loader_framework_refresh_replaces_adapter_snapshot(tmp_path, network, monkeypatch):
    from iaudit_eval.datasets import load

    dataset = load("tofueval", data_root=tmp_path)
    module = sys.modules[type(dataset.adapter).__module__]
    real_download = module.download_module.download

    def offline_download(data_dir, progress):
        return real_download(data_dir, progress, metadata=network[0], transport=network[3])

    monkeypatch.setattr(module.download_module, "download", offline_download)
    assert framework.download(dataset, data_root=tmp_path)["status"] == "ready"
    item = next(i for i in dataset.items("dev") if i.meta["dataset"] == "meetingbank")
    before = dataset.adapter.to_request(item)
    other = load("tofueval", data_root=tmp_path)
    assert other.adapter.to_request(item) == before
    # Force a refresh and change one document in the fictional upstream body.
    (tmp_path / "tofueval/meetingbank/test.json").write_text("tampered")
    rows = [json.loads(line) for line in network[1]["test.json"].splitlines()]
    for row in rows:
        if row["uid"] == item.doc_id:
            row["transcript"] = "New fictional council evidence."
    network[1]["test.json"] = b"\n".join(json.dumps(row).encode() for row in rows)
    assert framework.download(dataset, data_root=tmp_path)["status"] == "ready"
    after = dataset.adapter.to_request(item)
    assert after["transcript"] == [
        {"id": "t0", "speaker": "unlabeled", "text": "New fictional council evidence."}
    ]
    assert other.adapter.to_request(item) == after
