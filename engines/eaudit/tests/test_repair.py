import pytest

from eaudit.assembler.claims import LocatedClaim
from eaudit.assembler.evidence import EvidenceResult
from eaudit.assembler.models import AssembleReport, ClaimDraft, ConcernDraft
from eaudit.assembler.repair import repair_claim
from eaudit.contract import validate_response


def item(i, role):
    sp = {"start": {"index": 0, "char": 0}, "end": {"index": 0, "char": 3}}
    return {"id": f"e{i}", "role": role, "span": sp}


def evres(**roles):
    """evres(a='supporting', b='contradicting') -> items e1,e2 and key_ids a->e1, b->e2."""
    res = EvidenceResult()
    for n, (k, role) in enumerate(roles.items(), 1):
        res.items.append(item(n, role))
        res.key_ids[k] = [f"e{n}"]
    return res


def concern(t="timeframe_mismatch", *keys):
    return ConcernDraft(type=t, explanation="x", evidence_keys=list(keys))


def go(verdict="supported", ev=None, concerns=(), **kw):
    ev = ev or EvidenceResult()
    draft = ClaimDraft(
        key="k",
        section_index=0,
        segments=["s"],
        verdict=verdict,
        explanation="orig",
        suggested_revision=kw.pop("rev", "a rewrite"),
        concerns=list(concerns),
        **kw,
    )
    r = AssembleReport()
    out = repair_claim(LocatedClaim(draft, 0, 0, 3, id="c1"), ev, r)
    full = {
        "schema_version": "0.0.1",
        "status": "complete",
        "warnings": [],
        "claims": [
            {
                "id": "c1",
                "span": {"start": {"index": 0, "char": 0}, "end": {"index": 0, "char": 3}},
                **out.claim,
            }
        ],
    }
    assert validate_response(full) == [], out.claim
    return out, r


def test_clean_supported_untouched():
    out, r = go("supported", evres(a="supporting"), [concern("timeframe_mismatch", "a")])
    c = out.claim
    assert c["verdict"] == "supported" and c["explanation"] == "orig"
    assert c["concerns"][0]["evidence_ids"] == ["e1"]
    assert c["suggested_revision"] == "a rewrite" and out.notes == [] and not r.repairs


def test_concern_with_all_keys_dropped_is_removed():
    out, r = go(
        "partially_supported",
        evres(a="supporting"),
        [concern("timeframe_mismatch", "gone"), concern("context_stripping", "a")],
    )
    assert [c["type"] for c in out.claim["concerns"]] == ["context_stripping"]
    assert r.repairs["concern_removed"] == 1


def test_concern_without_keys_originally_stays():
    out, _ = go("insufficient_evidence", None, [concern("unsupported_claim")])
    assert out.claim["concerns"][0]["evidence_ids"] == []


def test_duplicate_concern_types_merge():
    ev = evres(a="supporting", b="supporting")
    out, _ = go(
        "partially_supported",
        ev,
        [concern("context_stripping", "a"), concern("context_stripping", "b")],
    )
    (c,) = out.claim["concerns"]
    assert c["evidence_ids"] == ["e1", "e2"]


def test_supported_without_support_becomes_insufficient():
    out, r = go("supported", evres(a="qualifying"))
    c = out.claim
    assert c["verdict"] == "insufficient_evidence"
    assert c["explanation"] != "orig" and c["suggested_revision"] is None
    assert any(x["type"] == "unsupported_claim" and x["evidence_ids"] == [] for x in c["concerns"])
    assert out.notes and r.repairs["supported_no_support"] == 1


def test_supported_with_contradicting_becomes_partial():
    out, r = go("supported", evres(a="supporting", b="contradicting"))
    c = out.claim
    assert c["verdict"] == "partially_supported"
    assert any(
        x["type"] == "contradictory_evidence" and x["evidence_ids"] == ["e2"] for x in c["concerns"]
    )
    assert r.repairs["supported_with_contradiction"] == 1


def test_supported_with_only_contradicting_ends_contradicted():
    out, _ = go("supported", evres(b="contradicting"))
    assert out.claim["verdict"] == "contradicted"


def test_contradicted_without_contradicting_becomes_insufficient():
    out, r = go("contradicted", evres(a="supporting"))
    c = out.claim
    assert c["verdict"] == "insufficient_evidence"
    assert [e["role"] for e in c["evidence"]] == ["supporting"]
    assert r.repairs["contradicted_no_contradiction"] == 1


def test_contradicted_with_contradicting_untouched():
    out, _ = go("contradicted", evres(b="contradicting"))
    assert out.claim["verdict"] == "contradicted" and out.claim["explanation"] == "orig"


def test_partial_without_concerns_becomes_insufficient():
    out, r = go("partially_supported", evres(a="supporting"))
    assert out.claim["verdict"] == "insufficient_evidence"
    assert r.repairs["partial_no_concerns"] == 1


def test_partial_whose_concerns_all_dropped_becomes_insufficient():
    out, _ = go("partially_supported", evres(a="supporting"), [concern("context_stripping", "zz")])
    assert out.claim["verdict"] == "insufficient_evidence"


def test_insufficient_with_contradicting_becomes_contradicted():
    out, r = go("insufficient_evidence", evres(b="contradicting"))
    assert out.claim["verdict"] == "contradicted"
    assert r.repairs["insufficient_with_contradiction"] == 1


def test_insufficient_with_no_evidence_is_fine():
    out, r = go("insufficient_evidence")
    assert out.claim["verdict"] == "insufficient_evidence" and not r.repairs


def test_out_of_scope_strips_concerns_and_evidence():
    out, _ = go(
        "out_of_scope",
        evres(a="supporting"),
        [concern("timeframe_mismatch", "a")],
    )
    c = out.claim
    assert c["concerns"] == [] and c["evidence"] == []
    assert c["out_of_scope_reason"]


def test_out_of_scope_keeps_given_reason():
    out, _ = go("out_of_scope", out_of_scope_reason="diagnostic criterion")
    assert out.claim["out_of_scope_reason"] == "diagnostic criterion"


def test_other_verdicts_strip_out_of_scope_reason():
    out, _ = go("insufficient_evidence", out_of_scope_reason="leftover")
    assert "out_of_scope_reason" not in out.claim


def test_stalled_claim():
    out, r = go("supported", evres(a="supporting"), outcome="stalled")
    c = out.claim
    assert c["verdict"] == "insufficient_evidence" and c["evidence"] == [] and c["concerns"] == []
    assert out.notes and r.repairs["stalled"] == 1


@pytest.mark.parametrize(
    "v",
    ["supported", "partially_supported", "contradicted", "insufficient_evidence", "out_of_scope"],
)
@pytest.mark.parametrize(
    "roles",
    [
        {},
        {"a": "supporting"},
        {"a": "contradicting"},
        {"a": "qualifying"},
        {"a": "supporting", "b": "contradicting"},
    ],
)
def test_never_upgrades_to_supported(v, roles):
    out, _ = go(v, evres(**roles))
    if v != "supported":
        assert out.claim["verdict"] != "supported"
    else:
        # supported survives only with support and no contradiction
        ok = "supporting" in roles.values() and "contradicting" not in roles.values()
        assert (out.claim["verdict"] == "supported") == ok


def test_conflict_repairs_use_their_own_warning_text():
    changed, _ = go("supported", evres(a="qualifying"))
    conflict, _ = go("supported", evres(a="supporting", b="contradicting"))
    conflict5, _ = go("insufficient_evidence", evres(b="contradicting"))
    assert conflict.notes == conflict5.notes
    assert conflict.notes != changed.notes
    assert "contradict" in conflict.notes[0].lower()
