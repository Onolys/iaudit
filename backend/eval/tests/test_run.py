"""The CLI: modes, replay vs live, recording and freshness, the POC gate, reports, baselines."""

import json
import re

import pytest

from eval import run as run_mod
from eval.baselines import BaselineNotInstalled, get_baseline, run_baseline
from eval.compare import deltas, render
from eval.run import main
from iaudit_backend.check.models import VerifierOutput
from iaudit_backend.llm import LLMResult


class FakeLive:
    """A pretend provider: every evidence item entails the claim."""

    def __init__(self):
        self.calls = 0

    async def complete_json(self, req, metrics=None):
        self.calls += 1
        keys = list(dict.fromkeys(re.findall(r"c\d+\.\d+:e\d+", req.user)))
        out = {"items": [{"key": k, "relation": "entails", "conf": "high"} for k in keys]}
        return LLMResult(parsed=VerifierOutput.model_validate(out), model="fake")


def run(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr().out


# -- oracle and reports ----------------------------------------------------------------------


def test_oracle_passes_the_poc_gate_and_writes_reports(tmp_path, capsys):
    code, out = run(["--mode", "oracle", "--gate", "poc", "--out", str(tmp_path)], capsys)
    assert code == 0 and out.count("PASS") == 9 and "FAIL" not in out
    assert "adhd-multi: skipped" in out and "cdr: not built" in out
    rep = json.loads((tmp_path / "oracle" / "report.json").read_text())
    assert rep["split"] == "poc-all" and rep["errors"] == [] and rep["mode"] == "oracle"
    md = (tmp_path / "report.md").read_text()
    assert (
        "poc-all" in md
        and "No overall score" in md
        and "| 7 | frequency_severity_inflation |" in md
    )
    rows = (tmp_path / "oracle" / "claims.jsonl").read_text().splitlines()
    assert rows and all("text" not in json.loads(r) for r in rows)


def test_reports_carry_no_transcript_text(tmp_path, capsys):
    main(["--mode", "oracle", "--out", str(tmp_path)])
    text = " ".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    for word in ("meetings", "phone", "paint", "groceries"):
        assert word not in text


def test_only_selects_fixtures_and_unknown_names_are_rejected(capsys):
    code, out = run(["--mode", "oracle", "--only", "v1,v3", "--gate", "poc"], capsys)
    assert code == 0 and out.count("PASS") == 2
    with pytest.raises(SystemExit):
        main(["--mode", "oracle", "--only", "nope"])


def test_noroles_variant_runs_but_is_not_gated(capsys):
    code, out = run(["--mode", "oracle", "--only", "v4-noroles", "--gate", "poc"], capsys)
    assert code == 0 and "PASS" not in out and "FAIL" not in out


def test_bad_arguments_exit_two(capsys):
    assert run(["--mode", "bogus"], capsys)[0] == 2
    assert run(["--record"], capsys)[0] == 2
    assert run(["--fixtures", "cdr"], capsys)[0] == 2


# -- replay ----------------------------------------------------------------------------------


def test_replay_gap_is_an_error_not_a_score(tmp_path, capsys):
    code, out = run(["--mode", "gold", "--only", "faithful", "--gate", "poc",
                     "--fixture-dir", str(tmp_path), "--out", str(tmp_path / "o")], capsys)  # fmt: skip
    assert code == 1 and "ERROR gold adhd-faithful: FixtureMiss" in out and "PASS" not in out
    rep = json.loads((tmp_path / "o" / "gold" / "report.json").read_text())
    assert rep["buckets"] == {} and rep["errors"][0]["fixture"] == "faithful"


# -- live, record, freshness -----------------------------------------------------------------


def test_live_refuses_without_keys_and_never_falls_back(monkeypatch, tmp_path, capsys):
    for k in run_mod.KEY_VARS:
        monkeypatch.delenv(k, raising=False)
    code, out = run(["--mode", "gold", "--live", "--fixture-dir", str(tmp_path)], capsys)
    assert code == 2 and "provider key" in out


def test_live_prints_a_cost_estimate_and_honours_max_cost(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    fake = FakeLive()
    monkeypatch.setattr(run_mod, "make_client", lambda s: fake)
    code, out = run(["--mode", "gold", "--live", "--max-cost", "0.01", "--only", "faithful",
                     "--fixture-dir", str(tmp_path)], capsys)  # fmt: skip
    assert code == 2 and "estimated cost: $" in out and fake.calls == 0


def test_live_record_then_replay_round_trip(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    fake = FakeLive()
    monkeypatch.setattr(run_mod, "make_client", lambda s: fake)
    d = str(tmp_path / "rec")
    code, out = run(["--mode", "gold", "--live", "--record", "--only", "faithful", "--gate", "poc",
                     "--fixture-dir", d], capsys)  # fmt: skip
    assert code == 0 and "PASS  gold  adhd-faithful" in out and fake.calls == 10
    manifest = json.loads((tmp_path / "rec" / "manifest.json").read_text())
    assert set(manifest["prompt_hashes"]) == {"atomize", "link", "check", "prep"}
    assert manifest["models"]["mid"] and manifest["date"]
    before = fake.calls
    code, out = run(["--mode", "gold", "--only", "faithful", "--gate", "poc", "--fixture-dir", d],
                    capsys)  # fmt: skip
    assert code == 0 and "PASS  gold  adhd-faithful" in out and fake.calls == before  # offline


def test_stale_prompt_hashes_warn_and_strict_fresh_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(run_mod, "make_client", lambda s: FakeLive())
    d = tmp_path / "rec"
    run(
        ["--mode", "gold", "--live", "--record", "--only", "faithful", "--fixture-dir", str(d)],
        capsys,
    )
    m = json.loads((d / "manifest.json").read_text())
    m["prompt_hashes"]["check"] = "0000"
    (d / "manifest.json").write_text(json.dumps(m))
    code, out = run(["--mode", "gold", "--only", "faithful", "--fixture-dir", str(d)], capsys)
    assert code == 0 and "Stale recordings: prompts changed for check" in out
    code, _ = run(["--mode", "gold", "--only", "faithful", "--fixture-dir", str(d),
                   "--strict-fresh"], capsys)  # fmt: skip
    assert code == 2


# -- baselines and compare -------------------------------------------------------------------


def test_registered_baselines_raise_with_an_install_note(capsys):
    for name in ("minicheck-flan-t5-l", "gpt-4o-mini"):
        with pytest.raises(BaselineNotInstalled, match="optional extra"):
            get_baseline(name)
    code, out = run(["--baseline", "minicheck-flan-t5-l"], capsys)
    assert code == 2 and "not installed" in out


def test_run_baseline_scores_bucket_one_in_the_report_shape():
    class Always:
        def predict(self, claim_text, evidence_text):
            return "not_supported"

    rep = run_baseline(Always(), [("a", "e", "supported"), ("b", "e", "not_supported"),
                                  ("c", "e", "not_supported")])  # fmt: skip
    row = rep["buckets"]["1"]
    assert (row["tp"], row["fp"], row["fn"]) == (2, 1, 0) and row["recall"] == 1.0
    assert row["precision"] == pytest.approx(2 / 3) and row["flags"] == ["indicative only (n < 5)"]


def test_bucket_one_inputs_come_from_gold_without_a_model():
    rows = run_mod.bucket1_inputs(["v1"])
    assert len(rows) == 10 and {r[2] for r in rows} == {"supported", "not_supported"}


def test_compare_flags_a_gain_of_at_least_five_points():
    def rep(f1_by_bucket):
        return {"buckets": {b: {"concern": "c", "f1": f} for b, f in f1_by_bucket.items()}}

    rows = deltas(rep({"7": 0.50, "5": 0.80, "3": None}), rep({"7": 0.55, "5": 0.81, "3": 0.9}))
    by = {r["bucket"]: r for r in rows}
    assert by["7"]["flag"] and by["7"]["delta"] == pytest.approx(0.05)
    assert not by["5"]["flag"] and by["3"]["delta"] is None
    assert "+0.05" in render(rows)
