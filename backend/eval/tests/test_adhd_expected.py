import json

import pytest

from eval.adhd import DATA
from eval.build_adhd import build

VERDICTS = {
    "supported",
    "partially_supported",
    "contradicted",
    "insufficient_evidence",
    "out_of_scope",
}
FIXTURES = ["faithful", *[f"v{i}" for i in range(1, 9)]]


def expected(fx):
    return json.loads(build()[f"expected/{fx}.json"])


def request(fx):
    return json.loads(build()[f"requests/{fx}.json"])


def test_nine_expected_files():
    assert sorted(k for k in build() if k.startswith("expected/")) == sorted(
        f"expected/{f}.json" for f in FIXTURES
    )


def test_faithful_expects_everything_supported_without_concerns():
    assert expected("faithful") == {
        "fixture": "adhd-faithful",
        "all_claims": {"verdict": "supported", "concerns_required": [], "concerns_allowed": []},
    }


@pytest.mark.parametrize("fx", FIXTURES[1:])
def test_variant_expected_is_well_formed(fx):
    e = expected(fx)
    assert e["fixture"] == f"adhd-{fx}"
    assert e["verdict"] in VERDICTS
    assert e["concerns_required"] and set(e) >= {
        "target_text",
        "concerns_allowed",
        "explanation_contains",
    }
    assert e["target_text"] in request(fx)["assessment"][0]["text"]


def test_expected_table_matches_prd():
    got = {f: (expected(f)["verdict"], expected(f)["concerns_required"]) for f in FIXTURES[1:]}
    assert got == {
        "v1": ("partially_supported", ["frequency_severity_inflation"]),
        "v2": ("contradicted", ["negation_reversal"]),
        "v3": ("contradicted", ["wrong_attribution"]),
        "v4": ("insufficient_evidence", ["question_as_answer"]),
        "v5": ("insufficient_evidence", ["timeframe_mismatch"]),
        "v6": ("partially_supported", ["conflicting_accounts_flattened"]),
        "v7": ("partially_supported", ["context_stripping"]),
        "v8": ("partially_supported", ["unsupported_causal_link"]),
    }
    assert expected("v2")["concerns_allowed"] == ["contradictory_evidence"]
    assert expected("v1")["explanation_contains"] == ["inflates"]


def test_expected_has_no_evidence_or_offsets():
    for fx in FIXTURES:
        keys = set(expected(fx)) | set(expected(fx).get("all_claims", {}))
        assert not keys & {"evidence", "start", "end", "slots", "claim_id"}


def test_committed_expected_files_match_builder():
    for rel, content in build().items():
        assert (DATA / rel).read_text(encoding="utf-8") == content, rel
