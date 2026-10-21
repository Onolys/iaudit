import dataclasses

import pytest

from iaudit_eval.datasets import load
from iaudit_eval.datasets.base import DatasetMeta, Item
from iaudit_eval.metrics import (
    BUILTIN_METRICS,
    DEFAULT_ITEM_LEVEL,
    LevelSpec,
    MetricEntry,
    Pair,
    Result,
    default_pairs,
    metrics_config,
)


def _item(**kw):
    base = dict(id="i1", doc_id="d1", split="dev", payload={}, meta={"topic": "garden"})
    return Item(**{**base, **kw})


def test_pair_frozen_and_meta_readonly():
    p = Pair("i1", "d1", "item", "", "flagged", "clean", None, {"topic": "x"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.gold = "clean"  # type: ignore[misc]
    with pytest.raises(TypeError):
        p.meta["topic"] = "y"  # type: ignore[index]
    src = {"topic": "x"}
    q = Pair("i1", "d1", "item", "", "a", "b", None, src)
    src["topic"] = "changed"
    assert q.meta["topic"] == "x"
    hash(dataclasses.replace(p, meta={}).level)


def test_levelspec_and_result_frozen():
    s = LevelSpec(labels=(False, True), positive=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.positive = False  # type: ignore[misc]
    assert LevelSpec.from_dict({"labels": ["a", "b"]}) == LevelSpec(("a", "b"), None)
    assert LevelSpec.from_dict({"labels": ["a", "b"], "positive": "b"}).positive == "b"
    with pytest.raises(ValueError):
        LevelSpec(("a", "b"), "c")
    with pytest.raises(dataclasses.FrozenInstanceError):
        Result(None, 0).n = 1  # type: ignore[misc]


def test_default_pairs_ok():
    (p,) = default_pairs(_item(), "flagged", "clean", None)
    assert (p.item_id, p.cluster, p.level, p.unit) == ("i1", "d1", "item", "")
    assert (p.gold, p.pred, p.failure) == ("flagged", "clean", None)
    assert p.meta == {"topic": "garden"}


def test_default_pairs_failed_keeps_gold():
    (p,) = default_pairs(_item(), "flagged", None, "item_failed")
    assert p.gold == "flagged" and p.pred is None and p.failure == "item_failed"


def test_default_pairs_rejects_inconsistent_failure():
    with pytest.raises(ValueError):
        default_pairs(_item(), "a", "b", "item_failed")
    with pytest.raises(ValueError):
        default_pairs(_item(), "a", None, None)


def test_cluster_is_doc_id_not_cluster_key():
    meta = DatasetMeta.from_dict({"name": "x", "cluster_key": "something"})
    cfg = metrics_config(meta)
    assert cfg.cluster_key == "something"
    (p,) = default_pairs(_item(doc_id="docZ"), "a", "b", None)
    assert p.cluster == "docZ"


def test_defaults_without_levels():
    cfg = metrics_config(DatasetMeta.from_dict({"name": "x"}))
    assert cfg.levels == {"item": DEFAULT_ITEM_LEVEL}
    assert DEFAULT_ITEM_LEVEL == LevelSpec((False, True), True)
    assert BUILTIN_METRICS == (
        "balanced_accuracy", "precision", "recall", "f1",
        "recall_by_type", "failure_rate", "coverage",
    )  # fmt: skip
    assert cfg.metrics == tuple(MetricEntry(n, n, "item", {}) for n in BUILTIN_METRICS)
    assert cfg.slices == () and cfg.references is None and cfg.pool_all is True


def test_defaults_every_declared_level():
    meta = DatasetMeta.from_dict({
        "name": "x",
        "levels": {"sentence": {"labels": [False, True], "positive": True},
                   "summary": {"labels": ["a", "b", "c"]}},
    })  # fmt: skip
    cfg = metrics_config(meta)
    assert list(cfg.levels) == ["sentence", "summary"]
    assert cfg.levels["summary"] == LevelSpec(("a", "b", "c"), None)
    assert len(cfg.metrics) == 2 * len(BUILTIN_METRICS)
    assert {m.level for m in cfg.metrics} == {"sentence", "summary"}


def test_explicit_metrics_and_keys():
    meta = DatasetMeta.from_dict({
        "name": "x",
        "levels": {"sentence": {"labels": [False, True], "positive": True}},
        "metrics": [
            {"name": "bacc_sentence", "fn": "balanced_accuracy", "level": "sentence"},
            {"name": "unresolved_rate", "fn": "failure_rate", "level": "sentence",
             "params": {"reason": "unresolved"}},
            {"name": "recall", "level": "sentence"},
        ],
        "slices": ["topic"], "references": "references.json", "pool_all": False,
        "cluster_key": "doc_id",
    })  # fmt: skip
    cfg = metrics_config(meta)
    assert cfg.metrics[0] == MetricEntry("bacc_sentence", "balanced_accuracy", "sentence", {})
    assert cfg.metrics[1].params == {"reason": "unresolved"}
    assert cfg.metrics[2].fn == "recall"  # fn defaults to name
    assert cfg.slices == ("topic",) and cfg.references == "references.json"
    assert cfg.pool_all is False


def test_explicit_empty_metrics_is_respected():
    cfg = metrics_config(DatasetMeta.from_dict({"name": "x", "metrics": []}))
    assert cfg.metrics == ()


def test_metric_level_must_be_declared():
    meta = DatasetMeta.from_dict({
        "name": "x", "levels": {"item": {"labels": [False, True]}},
        "metrics": [{"name": "recall", "level": "nope"}],
    })  # fmt: skip
    with pytest.raises(ValueError):
        metrics_config(meta)


def test_synthetic_metadata():
    cfg = metrics_config(load("synthetic").meta)
    assert cfg.levels["item"] == LevelSpec(("clean", "flagged"), "flagged")
    assert cfg.slices == ("topic",)
