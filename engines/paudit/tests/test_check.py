"""Task 12: live `paudit.cli check` pass/fail logic (offline, stub client) + a `live` wrapper.

The wrapper is skipped in PR CI (`-m "not live"`); real runs happen by hand per preset.
"""

import asyncio
from pathlib import Path

import pytest
import yaml
from onolys_core.llm import MetricsCollector, Usage

from paudit import check, cli
from paudit.pack import load_pack
from paudit.stub import ExpectedStubClient

pytestmark = pytest.mark.unit

PROTOCOLS = Path(__file__).resolve().parents[3] / "protocols"
FIX = PROTOCOLS / "miti-4.2.1" / "fixtures"
EXPECTED = FIX / "expected.yaml"


@pytest.fixture(scope="module")
def pack():
    return load_pack("miti@4.2.1", protocols_dir=PROTOCOLS)


def stub_factory(path=EXPECTED):
    return lambda name: ExpectedStubClient(path, name)


def thresholds(**over):
    t = yaml.safe_load((FIX / "thresholds.yaml").read_text())
    t.update(over)
    return t


def run(pack, factory, th=None):
    return asyncio.run(check.run_check(pack, FIX, factory, th or thresholds()))


def test_perfect_stub_passes_with_perfect_metrics(pack):
    rep = run(pack, stub_factory())
    assert rep.passed, rep.failures
    m = rep.metrics
    assert m["count_mae"] == 0
    assert m["globals_within_1"] == 1.0
    assert m["bad_output_rate"] == 0
    assert m["runs"] == 3
    assert {"p95_latency_s", "tokens_per_run"} <= set(m)
    assert "PASS" in check.format_report(rep)


def test_doctored_thresholds_make_it_fail(pack):
    rep = run(pack, stub_factory(), thresholds(count_mae_max=-1, tokens_per_run_max=-1))
    assert not rep.passed
    assert {f.metric for f in rep.failures} == {"count_mae", "tokens_per_run"}
    assert "FAIL" in check.format_report(rep)


def test_wrong_counts_and_globals_fail(pack, tmp_path):
    data = yaml.safe_load(EXPECTED.read_text())
    for fx in data["fixtures"].values():
        fx["utterances"] = []  # the stub then codes nothing -> every expected count is missed
        for g in fx["globals"].values():
            g["score"] = 1  # far outside the expected ranges
    doctored = tmp_path / "expected.yaml"
    doctored.write_text(yaml.safe_dump(data))

    rep = run(pack, stub_factory(doctored), thresholds(count_mae_max=0.5))  # vs real expected.yaml
    assert not rep.passed
    metrics = {f.metric for f in rep.failures}
    assert "count_mae" in metrics and "globals_within_1" in metrics


class SlowBad:
    """Wraps a stub: adds latency and token usage, and records one bad-output call per run."""

    def __init__(self, inner, latency_s):
        self.inner, self.latency_s = inner, latency_s

    async def complete_json(self, req, metrics: MetricsCollector | None = None):
        res = await self.inner.complete_json(req)
        if metrics is not None:
            metrics.record(req, "m", Usage(input_tokens=60000, output_tokens=1000), 5.0, 2, True)
            metrics.record(req, "m", Usage(), 1.0, 1, False, "bad_output")
        return res


def test_latency_tokens_and_bad_output_rate_are_enforced(pack):
    rep = run(pack, lambda n: SlowBad(ExpectedStubClient(EXPECTED, n), 0))
    assert rep.metrics["bad_output_rate"] == 1.0  # every call retried or bad
    assert rep.metrics["tokens_per_run"] >= 61000
    assert {f.metric for f in rep.failures} >= {"bad_output_rate"}
    ok = run(pack, lambda n: SlowBad(ExpectedStubClient(EXPECTED, n), 0),
             thresholds(bad_output_rate_max=1.0, tokens_per_run_max=10**7, p95_latency_s_max=1000))
    assert ok.passed


def test_p95_nearest_rank():
    assert check.p95([1.0]) == 1.0
    assert check.p95([1.0, 2.0, 3.0]) == 3.0
    assert check.p95(list(map(float, range(1, 21)))) == 19.0


def test_missing_threshold_key_is_an_error(pack):
    th = thresholds()
    del th["count_mae_max"]
    with pytest.raises(ValueError, match="count_mae_max"):
        run(pack, stub_factory(), th)


def test_main_exit_codes(capsys, tmp_path):
    base = ["check", "--pack", "miti@4.2.1", "--stub"]
    assert cli.main(base) == 0
    assert "PASS" in capsys.readouterr().out
    bad = tmp_path / "t.yaml"
    bad.write_text(yaml.safe_dump(thresholds(count_mae_max=-1)))
    assert cli.main([*base, "--thresholds", str(bad)]) == 1
    assert "count_mae" in capsys.readouterr().out


@pytest.mark.live
def test_live_check_default_preset():
    assert cli.main(["check", "--pack", "miti@4.2.1", "--preset", "default"]) == 0
