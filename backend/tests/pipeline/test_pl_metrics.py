import logging

from pl_scripted import Scripted

from iaudit_backend.models import AuditRequest
from iaudit_backend.pipeline.full import FullPipeline
from iaudit_backend.pipeline.metrics import STAGES


async def test_audit_done_line_carries_counters_and_no_text(make_ctx, caplog):
    s = Scripted()
    ctx = make_ctx(llm=s, request_id="adhd-faithful")
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("audit_done")]
    for field in (
        "sections_ok=1", "sections_failed=0", "claims_in_scope=11", "claims_oos=0",
        "claims_ok=11", "claims_stalled=0", "deadline_hit=0", "truncated=0", "calls=",
    ):  # fmt: skip
        assert field in line, field
    for stage in (*STAGES, "assemble", "total"):
        assert f"{stage}_ms=" in line
    for word in ("Alex", "meetings", "phone", "forgets"):
        assert word not in line


async def test_stage_spans_and_summary_are_stored_for_07(make_ctx):
    s = Scripted()
    ctx = make_ctx(llm=s, request_id="r")
    await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)
    m = ctx.extras["pipeline_metrics"]
    assert m["total_ms"] >= m["assemble_ms"] >= 0
    assert m["claims_ok"] == 11 and m["deadline_hit"] == 0
    st = ctx.extras["run_state"]
    assert set(st.spans) == set(STAGES)
    assert all(a <= b for a, b in st.spans.values())
