"""Hand-computed fictional scoring entries; no downloads or audit calls."""

import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from iaudit_eval.datasets.base import Dataset, DatasetMeta, Item
from iaudit_eval.metrics.pair import Pair, metrics_config
from iaudit_eval.scoring import _entries

EVAL = Path(__file__).resolve().parents[2]
DATASETS = EVAL / "datasets"


def dataset():
    raw = json.loads((DATASETS / "eaudit/tofueval/metadata.json").read_text())
    return Dataset(DatasetMeta.from_dict(raw), None)


def worked_pairs(monkeypatch, group="original_five", dataset="mediasum"):
    monkeypatch.syspath_prepend(str(EVAL))
    emit = importlib.import_module("datasets.eaudit.tofueval.pairs").pairs
    item = Item(f"fictional-{group}", f"doc-{group}", "dev", {}, {
        "model_group": group, "dataset": dataset, "topic_category": "main",
        "model_name": "fictional-model",
    })
    # Six sentences: EI detected, TAM unresolved, a false positive and three TNs.
    gold = {"summary": "inconsistent", "sentences": [
        {"sent_idx": i, "label": label, "types": types}
        for i, (label, types) in enumerate([
            ("inconsistent", ["Extrinsic Information"]), ("consistent", []),
            ("consistent", []), ("inconsistent", ["Tense/Modality"]),
            ("consistent", []), ("consistent", []),
        ])
    ]}
    prediction = {"summary": "inconsistent", "sentences": [
        {"sent_idx": i, "label": label, "meta": i == 4,
         "claim_ids": ids, "concerns": concerns, "boundary": i in (0, 1)}
        for i, (label, ids, concerns) in enumerate([
            ("inconsistent", ["a", "b"], ["unsupported_claim"]),
            ("consistent", ["b"], []), ("inconsistent", ["c"], []),
            ("unresolved", [], []), ("consistent", ["d"], []),
            ("consistent", ["e"], []),
        ])
    ], "claims_total": 7, "claims_unmapped": 2, "claims_boundary_crossing": 1,
        "concern_not_in_mapping": {"context_stripping": 2, "future_concern": 3}}
    return emit(item, gold, prediction, None)


def entry(entries, metric, *, level=None, policy="primary", slice=None):
    slice = slice or {"model_group": "original_five", "group_dataset": "original_five|mediasum"}
    found = [e for e in entries if e["metric"] == metric and e["policy"] == policy
             and e["slice"] == slice and (level is None or e["level"] == level)]
    assert len(found) == 1, (metric, level, policy, slice, found)
    return found[0]


def score_pairs(pairs):
    ds = dataset()
    return _entries(ds, metrics_config(ds.meta), pairs, DATASETS)


def test_worked_example_dual_policy_and_empty_detected_class(monkeypatch):
    entries = score_pairs(worked_pairs(monkeypatch))
    # TP=1 FN=1 FP=1 TN=3 -> (.5+.75)/2; excluding FN -> (1+.75)/2.
    assert entry(entries, "bacc_sentence")["value"] == 0.625
    assert entry(entries, "bacc_sentence", policy="secondary")["value"] == 0.875
    # Making the meta TN unresolved adds a primary FP -> (.5+.5)/2.
    assert entry(entries, "bacc_sentence_meta_unresolved")["value"] == 0.5
    for name in ("prec_inconsistent", "rec_inconsistent", "f1_inconsistent"):
        result = entry(entries, name, level="sentence")
        assert (result["value"], result["n"]) == (0.5, 2)
    assert entry(entries, "concern_match_rate_EI")["value"] == 1
    assert entry(entries, "concern_match_rate_TAM")["value"] == 0
    assert entry(entries, "concern_match_given_detected_EI")["n"] == 1
    missing = entry(entries, "concern_match_given_detected_TAM")
    assert (missing["value"], missing["n"], missing["ci"]) == (None, 0, None)
    assert (entry(entries, "rec_type_TAM")["value"], entry(entries, "rec_type_TAM")["n"]) == (0, 1)
    assert entry(entries, "rec_type_RE")["value"] is None
    assert entry(entries, "rec_type_RE")["n"] == 0
    assert entry(entries, "concern_match_base_rate_EI")["n"] == 4


def test_partition_is_explicit_everywhere_and_types_use_only_group_dataset(monkeypatch):
    pairs = worked_pairs(monkeypatch)
    extras = worked_pairs(monkeypatch, "model_extra")
    # Same model/dataset/topic names in both groups; all extra predictions are wrong.
    extras = [replace(p, pred="consistent" if p.gold == "inconsistent" else "inconsistent")
              if p.level == "sentence" and p.failure is None else p for p in extras]
    entries = score_pairs(pairs + extras)
    assert entries
    assert all({"metric", "value", "n", "ci", "slice", "impl"} <= e.keys() for e in entries)
    assert all(e["impl"] == "dataset:tofueval" for e in entries)
    assert all(e["slice"].get("model_group") in ("original_five", "model_extra") for e in entries)
    assert entry(entries, "bacc_sentence", slice={"model_group": "original_five", "dataset": "mediasum"})["value"] == 0.625
    assert entry(entries, "bacc_sentence", slice={"model_group": "model_extra", "dataset": "mediasum"})["value"] == 0
    assert entry(entries, "bacc_sentence", slice={"model_group": "original_five"})["n"] == 6
    typed = [e for e in entries if e["metric"].startswith(("rec_type_", "concern_match_"))]
    assert typed and all(set(e["slice"]) == {"model_group", "group_dataset"} for e in typed)
    # Paper references and live entries must have exactly the same slice shape.
    refs = json.loads((DATASETS / "eaudit/tofueval/references.json").read_text())["rows"]
    cell = next(r for r in refs if r["metric"] == "bacc_sentence" and r["slice"] == {
        "model_group": "original_five", "group_topic": "original_five|mediasum|main"})
    assert entry(entries, cell["metric"], slice=cell["slice"])["value"] == 0.625


def test_diagnostics_count_native_units_once_and_keep_unknown_names(monkeypatch):
    entries = score_pairs(worked_pairs(monkeypatch))
    for name, value, n in [
        ("claims_per_sentence", 1, 6), ("unmapped_claim_rate", 2 / 7, 7),
        ("boundary_crossing_rate", 1 / 7, 7), ("meta_consistent_n", 1, 6),
        ("concern_not_in_mapping", 5, 5),
        ("concern_not_in_mapping_context_stripping", 2, 5),
    ]:
        result = entry(entries, name, policy="none")
        assert (result["value"], result["n"]) == (value, n), name
    rate = entry(entries, "unresolved_rate", level="sentence", policy="none")
    assert (rate["value"], rate["n"]) == (1 / 6, 6)


def test_optional_partition_and_per_metric_slices_do_not_change_defaults():
    ds = Dataset(DatasetMeta.from_dict({
        "name": "none", "slices": ["topic", "model"],
        "metrics": [{"name": "all_topics", "fn": "recall"},
                    {"name": "models_only", "fn": "recall", "slices": ["model"]}],
    }), None)
    pairs = [Pair("a", "d", "item", "", True, True, None, {"topic": "x", "model": "m"})]
    entries = _entries(ds, metrics_config(ds.meta), pairs, DATASETS)
    assert [e["slice"] for e in entries if e["metric"] == "all_topics" and e["policy"] == "primary"] == [{}, {"topic": "x"}, {"model": "m"}]
    assert [e["slice"] for e in entries if e["metric"] == "models_only" and e["policy"] == "primary"] == [{}, {"model": "m"}]


@pytest.mark.parametrize("raw", ["model", [1]])
def test_invalid_per_metric_slice_declaration_rejected(raw):
    meta = DatasetMeta.from_dict({"name": "none", "metrics": [{"name": "recall", "slices": raw}]})
    with pytest.raises(ValueError, match="slices"):
        metrics_config(meta)


BACC_ALIASES = (
    "bacc_sentence", "bacc_summary",
    "bacc_sentence_meta_unresolved", "bacc_summary_meta_unresolved",
)


def bacc_entries(alias, observations):
    """Exercise real metadata, policy, aggregation and CI with fictional pairs."""
    ds = dataset()
    cfg = metrics_config(ds.meta)
    metric = next(m for m in cfg.metrics if m.name == alias)
    cfg = replace(cfg, metrics=(metric,))
    pairs = [
        Pair(f"fictional-{i}", f"doc-{i}", metric.level, "", gold, pred,
             "unresolved" if pred is None else None,
             {"model_group": "original_five", "group_dataset": "original_five|mediasum"})
        for i, (gold, pred) in enumerate(observations)
    ]
    return _entries(ds, cfg, pairs, DATASETS)


@pytest.mark.parametrize("alias", BACC_ALIASES)
@pytest.mark.parametrize("gold", ["consistent", "inconsistent"])
@pytest.mark.parametrize("n", [1, 5])
@pytest.mark.parametrize("policy", ["primary", "secondary"])
def test_bacc_missing_gold_class_is_undefined_with_observed_n(alias, gold, n, policy):
    # Even enough clusters for a CI cannot define the missing class's recall.
    result = entry(bacc_entries(alias, [(gold, gold)] * n), alias, policy=policy)
    assert (result["value"], result["n"], result["ci"], result["ci_status"]) == (
        None, n, None, "undefined",
    )


@pytest.mark.parametrize("alias", BACC_ALIASES)
@pytest.mark.parametrize("resolved, unresolved", [
    ("consistent", "inconsistent"), ("inconsistent", "consistent"),
])
def test_bacc_secondary_exclusion_can_remove_last_gold_class(alias, resolved, unresolved):
    entries = bacc_entries(alias, [(resolved, resolved), (unresolved, None)])
    # Primary recalls are 1 and 0; secondary leaves only the correct resolved unit.
    primary = entry(entries, alias)
    assert (primary["value"], primary["n"]) == (0.5, 2)
    secondary = entry(entries, alias, policy="secondary")
    assert (secondary["value"], secondary["n"], secondary["ci"], secondary["ci_status"]) == (
        None, 1, None, "undefined",
    )


@pytest.mark.parametrize("alias", BACC_ALIASES)
@pytest.mark.parametrize("policy", ["primary", "secondary"])
def test_bacc_both_gold_classes_keep_mean_recall(alias, policy):
    # Consistent recall 1/2, inconsistent recall 2/2 -> balanced accuracy .75.
    entries = bacc_entries(alias, [
        ("consistent", "consistent"), ("consistent", "inconsistent"),
        ("inconsistent", "inconsistent"), ("inconsistent", "inconsistent"),
    ])
    result = entry(entries, alias, policy=policy)
    assert (result["value"], result["n"]) == (0.75, 4)
