import json

from check_helpers import adhd_prep, claim, ev, link

from iaudit_backend.check.models import VerifierOutput
from iaudit_backend.check.verifier import (
    apply_floors,
    build_prompt,
    clean_output,
    load_fewshot,
    stage_block,
    verify,
)
from iaudit_backend.config import Settings
from iaudit_backend.llm import FailingClient, LLMBadOutput, LLMTimeout, LLMUnavailable, StubClient

PREP = adhd_prep(roles=True)


def item(key="c0.1:e1", **kw):
    return {"key": key, "relation": "entails", "polarity": "affirmed", **kw}


def stub(output, seen=None):
    c = StubClient()

    def fn(req):
        if seen is not None:
            seen.append(req)
        v = output.pop(0) if isinstance(output, list) else output
        return VerifierOutput.model_validate(v)

    c.register("check", fn)
    return c


def test_fewshot_is_fictional_prompt_split_and_validates():
    shots = load_fewshot()
    assert (
        json.load(
            open(
                __import__("iaudit_backend.check.verifier", fromlist=["x"]).PROMPTS
                / "check_fewshot.json"
            )
        )["split"]
        == "prompt"
    )
    for s in shots:
        VerifierOutput.model_validate(s["output"])
        assert "ADHD" not in json.dumps(s) and "Alex" not in json.dumps(s)
    assert any(not s["output"]["flags"] for s in shots)  # clean cases curb over-flagging
    assert "Output schema" in stage_block()


async def test_request_shape_whole_and_shortlist(make_ctx):
    for mode in ("whole", "shortlist"):
        seen: list = []
        lk = link(ev(), mode=mode)
        lk.shortlist = [2, 3]
        ctx = make_ctx(llm=stub({"items": [item()]}, seen))
        r = await verify(claim("Alex loses attention."), lk, PREP, PREP.turns, ctx)
        assert r.stall is None and len(r.output.items) == 1
        (req,) = seen
        assert (req.tier, req.call_tag, req.temperature) == ("mid", "check", 0.0)
        assert req.response_model is VerifierOutput and req.max_tokens == 1500
        assert req.fixture_key == "r1.check.c0.1" and req.deadline == ctx.deadline
        assert ("# Transcript" in req.cache_prefix) == (mode == "whole")
        assert "key=c0.1:e1" in req.user and "Most meetings." in req.user
        assert '<turn i="3"' in (req.cache_prefix if mode == "whole" else req.user)


def test_prompt_claim_block_is_last_so_prefix_is_claim_independent():
    a = build_prompt(claim("Alex naps."), link(ev()), PREP, PREP.turns)
    b = build_prompt(
        claim("He forgets.", cid="c0.2"), link(ev(cid="c0.2"), cid="c0.2"), PREP, PREP.turns
    )
    assert a[0] == b[0] and a[1] == b[1] and a[2] != b[2]


def test_inference_items_are_listed_with_premises():
    lk = link(
        ev(n=1),
        ev(n=2, turn=5),
        ev(n=3, lt="inference", premises=["c0.1:e1", "c0.1:e2"], step="Both."),
    )
    user = build_prompt(claim("x"), lk, PREP, PREP.turns)[2]
    assert "inference premises=c0.1:e1,c0.1:e2" in user


def test_clean_output_drops_unknown_keys_and_reports_unjudged():
    lk = link(ev(n=1), ev(n=2, turn=5))
    out = VerifierOutput.model_validate(
        {
            "items": [item("c0.1:e1"), item("zzz"), item("c0.1:e1")],
            "flags": [{"type": "element_gap", "keys": ["c0.1:e1", "nope"], "conf": "high"}],
        }
    )
    cleaned, missing = clean_output(out, lk)
    assert [i.key for i in cleaned.items] == ["c0.1:e1"] and missing == ["c0.1:e2"]
    assert cleaned.flags[0].keys == ["c0.1:e1"]


def test_floors_drop_and_count_low_confidence():
    out = VerifierOutput.model_validate(
        {
            "items": [item(conf="low"), item("c0.1:e2", conf="medium")],
            "flags": [
                {"type": "context_stripping", "keys": ["c0.1:e2"], "conf": "low"},
                {"type": "element_gap", "keys": [], "conf": "medium"},
            ],
            "inferences": [{"key": "c0.1:e3", "step_acceptable": True, "conf": "low"}],
        }
    )
    kept, counts = apply_floors(out, Settings())
    assert [i.key for i in kept.items] == ["c0.1:e2"]
    assert [f.type for f in kept.flags] == ["element_gap"]  # P1 at medium is emitted
    assert kept.inferences == []
    assert counts == {
        "items_below_floor": 1, "flags_seen": 2, "flags_below_floor": 1, "inferences_below_floor": 1,
    }  # fmt: skip


async def test_one_semantic_retry_for_unjudged_items(make_ctx):
    seen: list = []
    lk = link(ev(n=1), ev(n=2, turn=5))
    ctx = make_ctx(
        llm=stub(
            [{"items": [item("c0.1:e1")]}, {"items": [item("c0.1:e1"), item("c0.1:e2")]}], seen
        )
    )
    r = await verify(claim("x"), lk, PREP, PREP.turns, ctx)
    assert r.stall is None and r.retries == 1 and len(seen) == 2
    assert "c0.1:e2" in seen[1].user and seen[1].fixture_key == "r1.check.c0.1.retry"


async def test_still_unjudged_after_retry_stalls_bad_output(make_ctx):
    lk = link(ev(n=1), ev(n=2, turn=5))
    ctx = make_ctx(llm=stub({"items": [item("c0.1:e1")]}))
    r = await verify(claim("x"), lk, PREP, PREP.turns, ctx)
    assert (r.stall, r.unjudged, r.output) == ("bad_output", ["c0.1:e2"], None)


async def test_no_retry_when_disabled(make_ctx):
    seen: list = []
    lk = link(ev(n=1), ev(n=2, turn=5))
    ctx = make_ctx(llm=stub({"items": [item("c0.1:e1")]}, seen), check_retry=False)
    r = await verify(claim("x"), lk, PREP, PREP.turns, ctx)
    assert r.stall == "bad_output" and len(seen) == 1


async def test_llm_errors_stall(make_ctx):
    for exc, reason in [
        (LLMTimeout("t"), "timeout"),
        (LLMUnavailable("u"), "unavailable"),
        (LLMBadOutput("b"), "bad_output"),
    ]:
        ctx = make_ctx(llm=FailingClient(exc))
        r = await verify(claim("x"), link(ev()), PREP, PREP.turns, ctx)
        assert r.stall == reason


async def test_no_call_when_budget_is_exhausted(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub({"items": [item()]}, seen), deadline_in=0.5)
    r = await verify(claim("x"), link(ev()), PREP, PREP.turns, ctx)
    assert seen == [] and r.stall == "timeout"


async def test_missing_inference_judgment_is_retried_then_stalls(make_ctx):
    lk = link(
        ev(n=1), ev(n=2, turn=5),
        ev(n=3, lt="inference", premises=["c0.1:e1", "c0.1:e2"], step="Both."),
    )  # fmt: skip
    plain = {"items": [item("c0.1:e1"), item("c0.1:e2")]}
    full = {**plain, "inferences": [{"key": "c0.1:e3", "step_acceptable": True}]}
    seen: list = []
    r = await verify(claim("x"), lk, PREP, PREP.turns, make_ctx(llm=stub([plain, full], seen)))
    assert r.stall is None and r.retries == 1 and "c0.1:e3" in seen[1].user
    r = await verify(claim("x"), lk, PREP, PREP.turns, make_ctx(llm=stub(plain)))
    assert (r.stall, r.unjudged) == ("bad_output", ["c0.1:e3"])


def test_prompt_and_fewshot_cover_quantity_taxonomy():
    from iaudit_backend.check.verifier import PROMPTS

    sysmd = (PROMPTS / "check_system.md").read_text(encoding="utf-8")
    assert "- `quantity_mismatch`:" in sysmd and "ordinary rounding" in sysmd.lower()
    assert "another person or entity" in sysmd and "wider one" in sysmd
    assert "IGNORE amount" in sysmd
    shots = load_fewshot()
    flagged = {f["type"] for s in shots for f in s["output"]["flags"]}
    assert {"quantity_mismatch", "context_stripping"} <= flagged
    assert any(s["output"]["items"][0]["experiencer"] == "other_person" for s in shots)
    # a rate claim keeps frequency and raises no quantity flag
    rate = [s for s in shots if s["output"]["items"][0]["frequency"] and s["claim"]["quantities"]]
    assert any(
        all(f["type"] != "quantity_mismatch" for f in s["output"]["flags"]) for s in rate
    )
    # unscored speaker ids only
    assert {t["speaker"] for s in shots for t in s["turns"]} <= {"dr_vale", "jordan1"}
