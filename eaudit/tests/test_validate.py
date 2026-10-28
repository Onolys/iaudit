import copy

import pytest

from eaudit.assembler import (
    AssemblyError,
    ClaimDraft,
    InternalAudit,
    assemble,
)
from eaudit.assembler.validate import check_rules, finalize
from eaudit.config import Settings
from eaudit.contract import validate_response
from eaudit.models import AuditRequest


@pytest.fixture
def request_(example_request):
    return AuditRequest.model_validate(example_request)


@pytest.fixture
def good(example_response):
    return example_response


def test_example_response_passes_rules(request_, good):
    assert check_rules(request_, good) == []


def test_rule1_start_not_before_end(request_, good):
    good["claims"][0]["span"]["end"]["char"] = 0
    assert [p.claim for p in check_rules(request_, good)] == [0]


def test_rule1_span_past_input(request_, good):
    good["claims"][1]["evidence"][0]["span"]["end"]["char"] = 9999
    assert [p.claim for p in check_rules(request_, good)] == [1]


def test_rule1_claim_crosses_sections(request_, good):
    good["claims"][0]["span"]["end"]["index"] = 1
    assert check_rules(request_, good)


def test_rule1_cross_turn_end_at_zero(request_, good):
    good["claims"][2]["evidence"][0]["span"]["end"] = {"index": 3, "char": 0}
    assert [p.claim for p in check_rules(request_, good)] == [2]


def test_rule1_start_char_at_length_rejected(request_, good):
    n = len(request_.transcript[1].text)
    good["claims"][1]["evidence"][0]["span"]["start"]["char"] = n
    assert check_rules(request_, good)


def test_rule7_concern_points_at_foreign_id(request_, good):
    good["claims"][1]["concerns"][0]["evidence_ids"] = ["e-caregiver"]
    assert [p.claim for p in check_rules(request_, good)] == [1]


def test_rule7_duplicate_evidence_id(request_, good):
    good["claims"][0]["evidence"][1]["id"] = "e-caregiver"
    assert [p.claim for p in check_rules(request_, good)] == [0]


def test_rule7_duplicate_claim_id_flags_later(request_, good):
    good["claims"][1]["id"] = "c-supported"
    assert [p.claim for p in check_rules(request_, good)] == [1]


def test_rule8_overlap_flags_later_claim(request_, good):
    good["claims"][1]["span"]["start"]["char"] = 50
    assert [p.claim for p in check_rules(request_, good)] == [1]


def test_rule8_nesting(request_, good):
    good["claims"][1]["span"] = {
        "start": {"index": 0, "char": 5},
        "end": {"index": 0, "char": 20},
    }
    assert check_rules(request_, good)


def test_rule10_request_id(request_, good):
    good["request_id"] = "other"
    assert [p.claim for p in check_rules(request_, good)] == [None]
    good.pop("request_id")
    assert check_rules(request_, good)


def test_finalize_passes_valid_response_through(request_, good):
    assert finalize(request_, copy.deepcopy(good)) == good


def test_bad_claim_is_quarantined_with_warning(request_, good):
    good["claims"][3]["verdict"] = "supported"  # supported without supporting evidence
    out = finalize(request_, good)
    assert [c["id"] for c in out["claims"]] == [
        "c-supported",
        "c-contradicted",
        "c-partial",
        "c-oos",
    ]
    w = out["warnings"][-1]
    assert w["code"] == "other" and w["claim_id"] == "c-insufficient"
    assert validate_response(out) == []


def test_two_bad_claims_both_quarantined(request_, good):
    good["claims"][3]["verdict"] = "supported"
    good["claims"][4]["out_of_scope_reason"] = ""
    out = finalize(request_, good)
    assert len(out["claims"]) == 3 and len(out["warnings"]) == 2


def test_top_level_schema_error_raises(request_, good):
    good["status"] = "bogus"
    with pytest.raises(AssemblyError):
        finalize(request_, good)


def test_partial_without_warning_raises(request_, good):
    good["status"] = "partial"
    with pytest.raises(AssemblyError):
        finalize(request_, good)


def test_request_id_mismatch_raises(request_, good):
    good["request_id"] = "different"
    with pytest.raises(AssemblyError):
        finalize(request_, good)


def test_unfixable_after_quarantine_raises(request_, good):
    good["claims"][0]["verdict"] = "supported"
    good["claims"][0]["evidence"] = []
    good["warnings"] = [{"code": "other", "message": ""}]  # outside claims
    with pytest.raises(AssemblyError):
        finalize(request_, good)


def test_assembly_error_message_has_no_content(request_, good):
    good["status"] = "bogus-canary-value"
    with pytest.raises(AssemblyError) as ei:
        finalize(request_, good)
    assert "canary" not in str(ei.value)


def test_assemble_quarantines_bad_claim_end_to_end(example_request, monkeypatch):
    import eaudit.assembler as pkg
    from eaudit.assembler.repair import RepairedClaim

    def bad(lc, ev, report):
        return RepairedClaim(
            {
                "verdict": "supported",
                "explanation": "x",
                "suggested_revision": None,
                "concerns": [],
                "evidence": [],
            }
        )

    monkeypatch.setattr(pkg, "repair_claim", bad)
    d = ClaimDraft(
        key="a",
        section_index=0,
        segments=["The patient has trouble at work."],
        verdict="supported",
        explanation="e",
    )
    out = assemble(
        AuditRequest.model_validate(example_request), InternalAudit(claims=[d]), Settings()
    )
    assert out.response["claims"] == []
    assert out.response["warnings"][-1]["claim_id"] == "c1"
    assert validate_response(out.response) == []
