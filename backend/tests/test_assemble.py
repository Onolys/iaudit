import json

from iaudit_backend.assembler import (
    AssemblyError,
    ClaimDraft,
    ConcernDraft,
    EvidenceDraft,
    ExcerptSegment,
    InternalAudit,
    SectionFailure,
    assemble,
)
from iaudit_backend.assembler.locate import Match
from iaudit_backend.config import Settings
from iaudit_backend.contract import validate_response
from iaudit_backend.models import AuditRequest

CFG = Settings()


def req(example_request, extra_sections=()):
    for i, t in enumerate(extra_sections, 1):
        example_request["assessment"].append({"id": f"x{i}", "text": t})
    return AuditRequest.model_validate(example_request)


def ev(key, role, *segs, note=None):
    return EvidenceDraft(
        key=key,
        role=role,
        note=note,
        segments=[ExcerptSegment(turn_index=t, text=x) for t, x in segs],
    )


def cd(key, seg, verdict="insufficient_evidence", section=0, **kw):
    return ClaimDraft(
        key=key,
        section_index=section,
        segments=[seg],
        verdict=verdict,
        explanation="written in my own words",
        **kw,
    )


def run(example_request, internal, extra_sections=()):
    out = assemble(req(example_request, extra_sections), internal, CFG)
    assert validate_response(out.response) == [], out.response
    return out


def codes(resp):
    return [w["code"] for w in resp["warnings"]]


def test_failed_section_yields_warning_and_partial(example_request):
    internal = InternalAudit(
        claims=[cd("a", "The patient has trouble at work.")],
        section_failures=[SectionFailure(section_index=1, reason="timeout")],
    )
    out = run(example_request, internal, ["second section text"])
    w = out.response["warnings"][0]
    assert (w["code"], w["section_index"]) == ("section_not_processed", 1)
    assert out.response["status"] == "partial"


def test_no_failures_is_complete(example_request):
    out = run(example_request, InternalAudit(claims=[cd("a", "The patient has trouble at work.")]))
    assert out.response["status"] == "complete" and out.response["warnings"] == []


def test_section_without_located_claims_is_not_processed(example_request):
    internal = InternalAudit(claims=[cd("a", "The patient has trouble at work.")])
    out = run(example_request, internal, ["another section"])
    assert out.response["status"] == "partial"
    assert out.response["warnings"][0]["section_index"] == 1


def test_ambiguous_speaker_names_turns_not_text(example_request):
    d = cd("a", "The patient has trouble at work.", ambiguous_turns=[5, 5, 3])
    out = run(example_request, InternalAudit(claims=[d]))
    (w,) = out.response["warnings"]
    assert w["code"] == "ambiguous_speaker" and w["claim_id"] == "c1"
    assert "3" in w["message"] and "5" in w["message"]


def test_truncated_adds_input_truncated(example_request):
    out = run(
        example_request,
        InternalAudit(claims=[cd("a", "The patient has trouble at work.")], truncated=True),
    )
    assert codes(out.response) == ["input_truncated"] and out.response["status"] == "complete"


def test_unlocatable_claim_warns_without_text(example_request):
    internal = InternalAudit(
        claims=[
            cd("a", "The patient has trouble at work."),
            cd("b", "completely invented sentence here"),
        ]
    )
    out = run(example_request, internal)
    (w,) = out.response["warnings"]
    assert w["code"] == "other" and w["section_index"] == 0
    assert "invented" not in json.dumps(out.response)


def test_overlap_drop_warns_with_kept_claim_id(example_request):
    internal = InternalAudit(
        claims=[
            cd("a", "The patient has trouble at work.", verdict="supported"),
            cd("b", "The patient has trouble at work.", verdict="contradicted"),
        ]
    )
    out = run(example_request, internal)
    assert len(out.response["claims"]) == 1
    assert any(w["code"] == "other" and w.get("claim_id") == "c1" for w in out.response["warnings"])


def test_verdict_change_adds_claim_warning(example_request):
    d = cd("a", "The patient has trouble at work.", verdict="supported")
    out = run(example_request, InternalAudit(claims=[d]))
    c = out.response["claims"][0]
    assert c["verdict"] == "insufficient_evidence"
    assert [(w["code"], w["claim_id"]) for w in out.response["warnings"]] == [("other", "c1")]


def test_warning_order(example_request):
    internal = InternalAudit(
        claims=[
            cd("a", "The patient has trouble at work.", verdict="supported", ambiguous_turns=[5]),
            cd("b", "not anywhere in the text at all"),
        ],
        section_failures=[SectionFailure(section_index=1, reason="error")],
        truncated=True,
    )
    out = run(example_request, internal, ["second"])
    assert codes(out.response) == [
        "section_not_processed",
        "ambiguous_speaker",
        "other",  # verdict change for c1
        "input_truncated",
        "other",  # unlocatable draft b
    ]


def test_evidence_and_concern_ids_wired(example_request):
    d = cd(
        "a",
        "The patient frequently loses their keys.",
        verdict="contradicted",
        evidence=[ev("k1", "contradicting", (1, "I don't lose my keys"), note="A denial.")],
        concerns=[
            ConcernDraft(type="negation_reversal", explanation="reversed", evidence_keys=["k1"])
        ],
    )
    out = run(example_request, InternalAudit(claims=[d]))
    c = out.response["claims"][0]
    assert c["id"] == "c1" and c["evidence"][0]["id"] == "e1"
    assert c["concerns"][0]["evidence_ids"] == ["e1"]
    assert c["span"]["start"] == {"index": 0, "char": 57}


def test_out_of_range_span_dropped_with_warning(example_request, monkeypatch):
    import iaudit_backend.assembler.evidence as evmod

    monkeypatch.setattr(evmod, "locate", lambda t, n, h, c: Match(0, len(t) + 5, "exact", 100.0))
    d = cd(
        "a",
        "The patient has trouble at work.",
        verdict="contradicted",
        evidence=[ev("k1", "contradicting", (1, "I don't lose my keys"))],
    )
    out = run(example_request, InternalAudit(claims=[d]))
    c = out.response["claims"][0]
    assert c["evidence"] == [] and c["verdict"] == "insufficient_evidence"
    assert any(
        w["code"] == "span_out_of_range" and w["claim_id"] == "c1" for w in out.response["warnings"]
    )


def test_copy_check_applied(example_request):
    d = cd("a", "The patient has trouble at work.", suggested_revision="At 00:01:02 something")
    out = run(example_request, InternalAudit(claims=[d]))
    assert out.response["claims"][0]["suggested_revision"] is None


def test_report_has_no_canary_text(example_request):
    d = cd("a", "The patient has trouble at work.")
    out = run(example_request, InternalAudit(claims=[d]))
    assert "trouble" not in out.report.model_dump_json()


def test_assembly_error_is_runtime_error():
    assert issubclass(AssemblyError, RuntimeError)
