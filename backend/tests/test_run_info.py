"""run_info builder: models, prompt hashes, attach in the app."""

import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from iaudit_backend import contract, run_info
from iaudit_backend.app import create_app
from iaudit_backend.config import Settings
from iaudit_backend.models import AuditResponse

STAGES = {"atomize", "link", "check", "prep"}


def test_models_equal_configured_ids():
    s = Settings(model_cheap="a/x", model_mid="b/y", model_strong="c/z")
    assert run_info.build(s)["models"] == {"cheap": "a/x", "mid": "b/y", "strong": "c/z"}


def test_tokens_and_cost_never_populated():
    out = run_info.build(Settings())
    assert set(out) == {"models", "prompt_hashes"}
    assert set(out["prompt_hashes"]) == STAGES
    assert contract.validate_response(_resp(out)) == []


def _resp(ri):
    return {
        "schema_version": "1.2.0",
        "status": "complete",
        "warnings": [],
        "claims": [],
        "run_info": ri,
    }


def test_schema_accepts_tokens_and_cost_if_present():
    ri = run_info.build(Settings()) | {"input_tokens": 1, "output_tokens": 2, "cost_usd": 0.5}
    assert contract.validate_response(_resp(ri)) == []
    assert AuditResponse.model_validate(_resp(ri)).to_json()["run_info"] == ri


def test_hashes_equal_eval_manifest_algorithm():
    from eval.run import prompt_hashes

    assert run_info.prompt_hashes() == prompt_hashes()


def test_hashes_stable_across_processes():
    code = "from iaudit_backend import run_info as r; print(sorted(r.prompt_hashes().items()))"
    outs = [
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        for _ in range(2)
    ]
    assert outs[0].stdout == outs[1].stdout != ""
    assert outs[0].stdout.strip() == str(sorted(run_info.prompt_hashes().items()))


def test_editing_one_fewshot_changes_only_that_stage(tmp_path):
    shutil.copytree(run_info.PROMPTS, tmp_path / "p")
    d = tmp_path / "p"
    before = run_info.compute_hashes(d)
    assert before == run_info.prompt_hashes()
    f = d / "link_fewshot.json"
    f.write_bytes(f.read_bytes() + b" ")
    after = run_info.compute_hashes(d)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"link"}


@pytest.mark.parametrize("mode,present", [("full", True), ("stub", False)])
def test_attached_only_for_full_pipeline(example_request, mode, present):
    from iaudit_backend.pipeline import StubPipeline

    app = create_app(Settings(pipeline=mode, llm_mode="stub"), pipeline=StubPipeline())
    with TestClient(app) as c:
        r = c.post("/v1/audit", json=example_request)
    assert r.status_code == 200, r.text
    assert ("run_info" in r.json()) is present
