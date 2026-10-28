"""PRD worked example through the real offline store, registry and scoring path.

Catches dropped adapter hooks, changed projection/policy/concern wiring, and gold
text leaking into reports. All supplied source material is explicitly fictional.
"""

import csv
import json
import shutil
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from iaudit_eval import contracts, store
from iaudit_eval.datasets import load
from iaudit_eval.metrics.report import validate_item_rows, validate_metrics
from iaudit_eval.scoring import score

EVAL = Path(__file__).resolve().parents[2]
SOURCE_FIXTURES = EVAL / "tests/datasets/tofueval/fixtures"
WORKED = Path(__file__).with_name("fixtures") / "worked_example.json"


def test_saved_worked_example_scores_real_adapter_without_persisting_gold(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Offline acceptance must not contact any network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    worked = json.loads(WORKED.read_text())
    data = tmp_path / "data/tofueval"
    shutil.copytree(SOURCE_FIXTURES / "repo", data / "repo")
    csv_path = data / "repo/factual_consistency/mediasum_factual_eval_dev.csv"
    with csv_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        template = next(reader)
    # Replace only this local fictional summary; keep real C1 CSV/join loading.
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, sentence in enumerate(worked["sentences"], 1):
            writer.writerow({**template, **sentence, "sent_idx": index,
                             "annotation_id": f"fictional-worked-{index}"})
    (data / "derived").mkdir()
    (data / "derived/transcripts.json").write_text(json.dumps({
        f"mediasum:{template['doc_id']}": {"speaker": ["Fictional narrator"],
                                      "utt": ["The fictional kite has paper wings and a ribbon."]},
    }))
    dataset = load("tofueval", data_root=data.parent)
    item = next(item for item in dataset.items("dev") if item.doc_id == template["doc_id"])
    request = dataset.adapter.to_request(item)
    response = worked["response"]
    assert not contracts.validate_request(request)
    assert not contracts.validate_response(response)
    assert len(item.payload["sentences"]) == 6

    root, run_id = tmp_path / "runs", "fictional-worked"
    store.create_run(root, {
        "run_id": run_id, "dataset": "tofueval", "split": "dev",
        "item_ids": [item.id], "mapping_version": dataset.adapter.mapping_version(),
        "schema_version": contracts.schema_version(),
    })
    store.write_item(root, run_id, {
        "item_id": item.id, "status": "ok", "request": request, "response": response,
    })
    store.update_run(root, run_id, state="finished")
    saved = next(store.iter_items(root, run_id))
    assert not contracts.validate_request(saved["request"])
    assert not contracts.validate_response(saved["response"])
    report = score(run_id, runs_root=root, data_root=data.parent)
    persisted = json.loads((root / run_id / "metrics.json").read_text())
    rows = json.loads((root / run_id / "item_rows.json").read_text())
    validate_metrics(persisted)
    validate_item_rows(rows)
    assert report == persisted
    assert report["items"] == {"selected": 1, "scored": 1, "failed": 0, "not_run": 0}
    assert report["run"]["complete"] is True

    def entry(metric, policy="primary"):
        matches = [e for e in persisted["entries"] if e["metric"] == metric
                   and e["policy"] == policy and e["slice"] == {
                       "model_group": "original_five", "group_dataset": "original_five|mediasum"}]
        assert len(matches) == 1, (metric, policy, matches)
        return matches[0]

    # Gold inconsistent: s1 EI, s4 TAM. Predictions: TP,TN,FP,unresolved,meta TN,TN.
    # Primary TP=1 FN=1 FP=1 TN=3 -> (.5+.75)/2=.625 (n=6).
    # Secondary excludes s4 -> TP=1 FN=0 FP=1 TN=3 -> (1+.75)/2=.875 (n=5).
    # Meta alt turns s5 into unresolved/FP -> TP=1 FN=1 FP=2 TN=2 -> .5 (n=6).
    for metric, policy, value, n in [
        ("bacc_sentence", "primary", 0.625, 6),
        ("bacc_sentence", "secondary", 0.875, 5),
        ("bacc_sentence_meta_unresolved", "primary", 0.5, 6),
        ("meta_consistent_n", "none", 1, 6),
        # EI is detected with its allowed concern (1/1); TAM is unresolved (0/1).
        ("concern_match_rate_EI", "primary", 1, 1),
        ("concern_match_rate_TAM", "primary", 0, 1),
        ("concern_match_given_detected_EI", "primary", 1, 1),
        # No TAM sentence was detected, so conditional agreement has no population.
        ("concern_match_given_detected_TAM", "primary", None, 0),
    ]:
        result = entry(metric, policy)
        assert (result["value"], result["n"]) == (value, n), metric
        assert result["impl"] == "dataset:tofueval"
    assert entry("concern_match_given_detected_TAM")["ci"] is None
    assert all(e["slice"].get("model_group") == "original_five" for e in report["entries"])
    assert report["dataset_extra"]["mapping_version"] == "0.0.1"
    assert report["dataset_extra"]["mapping_sha256"] == "2c47702f2fb2a07e0b9ec3787ee700f5fafbd1c8f58d18638b61976e6daec303"
    assert len(rows["rows"]) == 1
    row = rows["rows"][0]
    assert row["item_id"] == item.id
    assert (row["outcome"], row["match"]) == ("tp", True)
    assert row["detail"]["pred"] == {
        "summary": "inconsistent", "n_inconsistent": 2, "n_unresolved": 1, "n_meta": 1,
    }
    assert [s["outcome"] for s in row["detail"]["sentences"]] == [
        "tp", "tn", "fp", "unresolved", "tn", "tn",
    ]
    serialized = json.dumps([persisted, rows])
    assert '"text"' not in serialized and '"exp"' not in serialized
    gold = dataset.adapter.gold(item)
    for source, sentence in zip(worked["sentences"], gold["sentences"], strict=True):
        assert sentence["text"] == source["summ_sent"]
        assert sentence["exp"] == source["exp"]
        assert sentence["text"] not in serialized
        assert sentence["exp"] not in serialized
    # Saved replay inputs retain the assessment; report privacy must not erase it.
    assert gold["sentences"][0]["text"] in saved["request"]["assessment"][0]["text"]


@pytest.mark.parametrize("module", ["metrics", "projection"])
def test_pure_module_imports_without_network_or_client_modules(module, tmp_path):
    # A fresh interpreter avoids a previously loaded adapter hiding an import.
    # Namespace loading bypasses adapter.py (which intentionally imports httpx).
    script = textwrap.dedent('''
        import importlib
        import importlib.abc
        import importlib.machinery
        import socket
        import sys
        import types

        sys.path.insert(0, sys.argv[3])
        forbidden = ("httpx", "httpcore", "requests", "urllib3", "aiohttp",
                     "openai", "anthropic", "litellm", "eaudit")
        def no_network(*args, **kwargs):
            raise AssertionError("Pure module import attempted network")
        socket.socket.connect = no_network
        socket.socket.connect_ex = no_network
        socket.getaddrinfo = no_network
        class Guard(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in forbidden:
                    raise AssertionError("Forbidden client/backend import: " + fullname)
        sys.meta_path.insert(0, Guard())
        package = types.ModuleType("fictional_tofueval")
        package.__path__ = [sys.argv[1]]
        package.__spec__ = importlib.machinery.ModuleSpec(
            package.__name__, loader=None, is_package=True)
        sys.modules[package.__name__] = package
        importlib.import_module("fictional_tofueval." + sys.argv[2])
        assert not any(name.split(".")[0] in forbidden for name in sys.modules)
        assert "fictional_tofueval.adapter" not in sys.modules
    ''')
    result = subprocess.run(
        [sys.executable, "-c", script, str(EVAL / "datasets/eaudit/tofueval"), module, str(EVAL / "src")],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
