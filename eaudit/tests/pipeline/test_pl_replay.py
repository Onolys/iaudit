"""Acceptance 1: ADHD faithful + 8 variants through FullPipeline match the 07 expectations."""

import json

import pytest
from pl_scripted import Scripted

from eaudit import contract
from eaudit.models import AuditRequest
from eaudit.pipeline.full import FullPipeline
from eval.adhd import DATA

VARIANTS = [f"v{i}" for i in range(1, 9)]


async def run(make_ctx, vid):
    s = Scripted(None if vid == "faithful" else vid)
    # the scripted request must be the committed fixture request, byte for byte
    committed = json.loads((DATA / "requests" / f"{vid}.json").read_text())
    assert s.request["assessment"][0]["text"] == committed["assessment"][0]["text"]
    ctx = make_ctx(llm=s, request_id=committed["request_id"])
    resp = await FullPipeline().run(AuditRequest.model_validate(committed), ctx)
    return committed, resp.to_json()


def target(committed, body, text):
    sec = committed["assessment"][0]["text"]
    (c,) = [
        c
        for c in body["claims"]
        if sec[c["span"]["start"]["char"] : c["span"]["end"]["char"]].strip() == text.strip(". ")
        or sec[c["span"]["start"]["char"] : c["span"]["end"]["char"]].strip(". ")
        == text.strip(". ")
    ]
    return c


async def test_faithful_claims_are_all_supported_without_concerns(make_ctx):
    committed, body = await run(make_ctx, "faithful")
    assert contract.validate_response(body) == []
    assert body["request_id"] == "adhd-faithful" and body["status"] == "complete"
    assert body["warnings"] == [] and len(body["claims"]) == 11
    for c in body["claims"]:
        assert (c["verdict"], c["concerns"]) == ("supported", [])


@pytest.mark.parametrize("vid", VARIANTS)
async def test_variant_matches_expected_verdict_and_concerns(make_ctx, vid):
    exp = json.loads((DATA / "expected" / f"{vid}.json").read_text())
    committed, body = await run(make_ctx, vid)
    assert contract.validate_response(body) == []
    assert body["request_id"] == f"adhd-{vid}"
    c = target(committed, body, exp["target_text"])
    assert c["verdict"] == exp["verdict"]
    got = {x["type"] for x in c["concerns"]}
    assert (
        set(exp["concerns_required"])
        <= got
        <= set(exp["concerns_required"]) | set(exp["concerns_allowed"])
    )
    blob = c["explanation"] + " ".join(x["explanation"] for x in c["concerns"])
    for needle in exp["explanation_contains"]:
        assert needle in blob
    others = [x for x in body["claims"] if x is not c]
    assert {x["verdict"] for x in others} <= {"supported"}  # the one edit is the only finding
