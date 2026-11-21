"""Task 11: synthetic fixtures, expected.yaml, thresholds, offline CLI `run`, replay golden.

Everything here is offline: the stub answers with the intended codes written in expected.yaml;
the golden is a stub recording (no live model), replayed through core's FixtureClient.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml
from onolys_core.llm import FixtureClient
from onolys_core.transcript import Transcript

from paudit import cli
from paudit.engine import run
from paudit.pack import load_pack
from paudit.result import schema_text
from paudit.stub import ExpectedStubClient

pytestmark = pytest.mark.unit

PROTOCOLS = Path(__file__).resolve().parents[3] / "protocols"
FIX = PROTOCOLS / "miti-4.2.1" / "fixtures"
NAMES = ["good_practice", "poor_practice", "short_session"]
GOLDEN = FIX / "golden" / "good_practice"


def expected():
    return yaml.safe_load((FIX / "expected.yaml").read_text())


def load(name):
    t = Transcript.model_validate_json((FIX / f"{name}.json").read_text())
    params = json.loads((FIX / f"{name}.params.json").read_text())
    return t, params


@pytest.fixture(scope="module")
def pack():
    return load_pack("miti@4.2.1", protocols_dir=PROTOCOLS)


def stub_run(pack, name):
    t, params = load(name)
    client = ExpectedStubClient(FIX / "expected.yaml", name)
    return asyncio.run(run(t, pack, params, client))


@pytest.mark.parametrize("name", NAMES)
def test_fixture_is_labelled_synthetic_and_quotes_locate(name):
    raw = json.loads((FIX / f"{name}.json").read_text())
    assert raw["synthetic"] is True and raw["description"]
    exp = expected()["fixtures"][name]
    turns = {t["id"]: t for t in raw["turns"]}
    cursor = {}
    for u in exp["utterances"]:
        text = turns[u["turn_id"]]["text"]
        start = text.index(u["quote"], cursor.get(u["turn_id"], 0))
        cursor[u["turn_id"]] = start + len(u["quote"])
    clin = {t["id"] for t in raw["turns"] if t["speaker"] == "A"}
    assert clin == {u["turn_id"] for u in exp["utterances"]}


@pytest.mark.parametrize("name", NAMES)
def test_stub_run_matches_expected(pack, name):
    exp = expected()["fixtures"][name]
    res = stub_run(pack, name)
    jsonschema.validate(json.loads(res.model_dump_json()), json.loads(schema_text()))
    only = res.results[0]
    assert only.counts == exp["counts"]
    for sid, val in exp["summaries"].items():
        got = only.summaries[sid].value
        assert (got is None) if val is None else got == pytest.approx(val)
    for gid, g in exp["globals"].items():
        assert only.globals[gid].score == g["score"]
        assert g["range"][0] <= g["score"] <= g["range"][1]
    assert sorted({w.code for w in res.warnings + only.warnings}) == sorted(exp["warnings"])


def test_short_fixture_yields_short_session_only_there(pack):
    codes = {n: {w.code for w in stub_run(pack, n).warnings} for n in NAMES}
    assert "short_session" in codes["short_session"]
    assert "short_session" not in codes["good_practice"] | codes["poor_practice"]


def test_poor_fixture_exercises_rules(pack):
    only = stub_run(pack, "poor_practice").results[0]
    reasons = {i.uncounted_reason for i in only.instances}
    assert "duplicate_in_volley" in reasons
    assert only.counts["persuade"] >= 1 and only.counts["confront"] >= 1


def test_good_fixture_reflection_supersede(pack):
    only = stub_run(pack, "good_practice").results[0]
    assert any(i.uncounted_reason == "superseded_by_cr" for i in only.instances)


def test_thresholds_file():
    th = yaml.safe_load((FIX / "thresholds.yaml").read_text())
    assert {
        "count_mae_max",
        "globals_within_1_min",
        "bad_output_rate_max",
        "p95_latency_s_max",
        "tokens_per_run_max",
    } <= set(th)
    assert all(isinstance(v, int | float) and v > 0 for v in th.values())


def test_golden_replay_twice_identical(pack):
    t, params = load("good_practice")
    client = FixtureClient(GOLDEN)
    a = asyncio.run(run(t, pack, params, client))
    b = asyncio.run(run(t, pack, params, FixtureClient(GOLDEN)))
    assert a.model_dump_json() == b.model_dump_json()
    # the recording came from the stub, so it matches the stub-driven result too
    exp = expected()["fixtures"]["good_practice"]
    assert a.results[0].counts == exp["counts"]
    jsonschema.validate(json.loads(a.model_dump_json()), json.loads(schema_text()))


def test_cli_run_offline_stub(capsys, tmp_path):
    out = tmp_path / "res.json"
    rc = cli.main(
        [
            "run", "--pack", "miti@4.2.1",
            "--transcript", str(FIX / "poor_practice.json"),
            "--params", str(FIX / "poor_practice.params.json"),
            "--stub", str(FIX / "expected.yaml"),
            "--out", str(out),
        ]
    )  # fmt: skip
    assert rc == 0
    res = json.loads(out.read_text())
    jsonschema.validate(res, json.loads(schema_text()))
    assert res["results"][0]["counts"] == expected()["fixtures"]["poor_practice"]["counts"]


def test_cli_module_subprocess_stdout_and_replay():
    base = [
        sys.executable, "-m", "paudit.cli", "run", "--pack", "miti@4.2.1",
        "--transcript", str(FIX / "good_practice.json"),
        "--params", str(FIX / "good_practice.params.json"),
    ]  # fmt: skip
    for extra in (["--stub", str(FIX / "expected.yaml")], ["--replay", str(GOLDEN)]):
        proc = subprocess.run(
            [*base, *extra], capture_output=True, text=True, check=False, timeout=120
        )
        assert proc.returncode == 0, proc.stderr
        res = json.loads(proc.stdout)
        assert res["results"][0]["counts"] == expected()["fixtures"]["good_practice"]["counts"]


def test_cli_bad_input_exits_nonzero(capsys, tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps({"speaker_map": {"subject": "A"}}))  # no change_goal
    rc = cli.main(
        [
            "run", "--pack", "miti@4.2.1",
            "--transcript", str(FIX / "good_practice.json"),
            "--params", str(bad),
            "--stub", str(FIX / "expected.yaml"),
            "--stub-fixture", "good_practice",
        ]
    )  # fmt: skip
    assert rc != 0
    assert "change_goal" in capsys.readouterr().err
