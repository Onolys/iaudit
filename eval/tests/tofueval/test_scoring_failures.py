"""Failure accounting and saved-request guards on the real TofuEval scoring path (fictional data)."""

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from iaudit_eval import contracts, store
from iaudit_eval.datasets import load
from iaudit_eval.scoring import score

FIXTURES = Path(__file__).resolve().parents[1] / "datasets/tofueval/fixtures"


@pytest.fixture
def dataset(tmp_path):
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


def response_covering(item, upto):
    end = item.payload["sentences"][upto - 1]["end"]
    return {"claims": [{
        "id": "c1",
        "span": {"start": {"index": 0, "char": 0}, "end": {"index": 0, "char": end}},
        "verdict": "supported", "explanation": "Fictional.", "concerns": [], "evidence": [],
    }]}


def run(tmp_path, dataset, entries):
    """entries: list of (item, status, response, request_override)."""
    root = tmp_path / "runs"
    store.create_run(root, {
        "run_id": "r1", "dataset": "tofueval", "split": "all",
        "item_ids": [e[0].id for e in entries],
        "mapping_version": dataset.adapter.mapping_version(),
        "schema_version": contracts.schema_version(),
    })
    for item, status, response, request in entries:
        store.write_item(root, "r1", {
            "item_id": item.id, "status": status,
            "request": request or dataset.adapter.to_request(item), "response": response,
        })
    store.update_run(root, "r1", state="finished")
    return root


def test_by_reason_counts_native_level_once_and_not_failed_items(tmp_path, dataset):
    items = dataset.items("all")
    ok = max(items, key=lambda i: len(i.payload["sentences"]))
    others = [i for i in items if i is not ok][:2]
    n = len(ok.payload["sentences"])
    assert n >= 2
    root = run(tmp_path, dataset, [
        (ok, "ok", response_covering(ok, n - 1), None),
        (others[0], "failed", None, None),
        (others[1], "failed", None, None),
    ])
    rep = score("r1", runs_root=root, data_root=tmp_path)
    assert rep["items"]["scored"] == 1 and rep["items"]["failed"] == 2
    # Only the scored item's one uncovered sentence, counted once at the native sentence level.
    assert rep["failures"]["by_reason"] == {"item_failed": 2, "unmapped": 0, "unresolved": 1}


def test_saved_request_text_mismatch_is_a_distinct_item_failure(tmp_path, dataset):
    items = dataset.items("all")
    good, stale = items[0], items[1]
    stale_request = dataset.adapter.to_request(stale)
    stale_request["assessment"][0]["text"] += " Edited after the run."
    n = len(good.payload["sentences"])
    m = len(stale.payload["sentences"])
    root = run(tmp_path, dataset, [
        (good, "ok", response_covering(good, n), None),
        (stale, "ok", response_covering(stale, m), stale_request),
    ])
    rep = score("r1", runs_root=root, data_root=tmp_path)
    assert rep["items"]["scored"] == 1 and rep["items"]["failed"] == 1
    assert rep["failures"]["by_reason"]["request_mismatch"] == 1
    assert rep["failures"]["by_reason"]["unresolved"] == 0
    rows = {r["item_id"]: r for r in json.loads((root / "r1" / "item_rows.json").read_text())["rows"]}
    assert rows[stale.id]["status"] == "failed"
    assert rows[good.id]["status"] == "ok"
