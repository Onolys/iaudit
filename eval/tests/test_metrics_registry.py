from collections import Counter

import pytest

from iaudit_eval.metrics import registry as reg
from iaudit_eval.metrics.pair import LevelSpec, Pair, Result
from iaudit_eval.metrics.registry import Metric, combine, metric, pairwise, resolve

SPEC = LevelSpec((False, True), True)


def P(gold, pred):
    return Pair("i", "d", "item", "", gold, pred, None)


@pytest.fixture
def clean_registry():
    saved = dict(reg._CORE)
    yield
    reg._CORE.clear()
    reg._CORE.update(saved)


def _make(tmp_path, name, body):
    d = tmp_path / name
    d.mkdir()
    (d / "metrics.py").write_text(body)
    return tmp_path


def test_decorator_registers_and_resolves_core(clean_registry):
    @metric("hits", policy="primary_secondary")
    class Hits:
        @staticmethod
        def stat(pairs, spec, **params):
            return Counter(n=len(pairs), ok=sum(p.gold == p.pred for p in pairs))

        @staticmethod
        def finalize(stats, spec, **params):
            return Result(stats["ok"] / stats["n"] if stats["n"] else None, stats["n"])

    r = resolve("hits", "nodataset", root=None)
    assert r.impl == "core" and r.metric.policy == "primary_secondary"
    st = r.metric.stat([P(True, True), P(True, False)], SPEC)
    assert r.metric.finalize(st, SPEC) == Result(0.5, 2)


def test_bad_policy_and_duplicate(clean_registry):
    with pytest.raises(ValueError):
        metric("x", policy="bogus")
    metric("dup", policy="none")(_cls())
    with pytest.raises(ValueError):
        metric("dup", policy="none")(_cls())


def _cls():
    class C:
        stat = staticmethod(lambda pairs, spec, **p: Counter())
        finalize = staticmethod(lambda stats, spec, **p: Result(None, 0))

    return C


def test_unregistered_core_name_clear_error(clean_registry):
    with pytest.raises(KeyError, match="nope"):
        resolve("nope", "nodataset")


def test_alias_needs_no_code(clean_registry):
    r = resolve("balanced_accuracy", "ds")  # entry fn; entry name 'bacc_sentence' is only reported
    assert r.impl == "core"


def test_dataset_override_wins(clean_registry, tmp_path):
    root = _make(
        tmp_path,
        "ds1",
        "from collections import Counter\n"
        "from iaudit_eval.metrics.registry import metric\n"
        "from iaudit_eval.metrics.pair import Result\n"
        "@metric('recall', policy='none', register=False)\n"
        "class R:\n"
        "    def stat(pairs, spec, **p): return Counter(n=1)\n"
        "    def finalize(stats, spec, **p): return Result(1.0, 1)\n"
        "METRICS = {'recall': R}\n",
    )
    r = resolve("recall", "ds1", root=root)
    assert r.impl == "dataset:ds1" and r.metric.policy == "none"
    assert resolve("recall", "other", root=root).impl == "core"
    assert resolve("recall", "ds1", root=root / "missing").impl == "core"
    # dataset without that name falls back to core
    _make(tmp_path, "ds2", "METRICS = {}\n")
    assert resolve("recall", "ds2", root=root).impl == "core"


def test_dataset_metrics_bad_module(clean_registry, tmp_path):
    root = _make(tmp_path, "bad", "raise RuntimeError('boom')\n")
    with pytest.raises(ValueError, match="bad"):
        resolve("recall", "bad", root=root)
    root2 = _make(tmp_path, "nometrics", "X = 1\n")
    with pytest.raises(ValueError, match="METRICS"):
        resolve("recall", "nometrics", root=root2)


def test_pairwise_wrapper():
    m = pairwise("pw", lambda pairs, **_: Result(float(len(pairs)), len(pairs)), policy="none")
    assert isinstance(m, Metric)
    a = m.stat([P(True, True)], SPEC)
    b = m.stat([P(True, True), P(False, False)], SPEC)
    assert m.finalize(combine(a, b), SPEC) == Result(3.0, 3)


def test_combine_counter_list_and_mismatch():
    assert combine(Counter(a=1), Counter(a=2, b=1)) == Counter(a=3, b=1)
    assert combine([1], [2]) == [1, 2]
    with pytest.raises(TypeError):
        combine(Counter(), [1])
