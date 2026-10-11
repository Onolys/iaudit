"""Basic per-request metrics: stage spans, counters, deadline_hit. Counts and durations only."""

from iaudit_backend.assembler import InternalAudit
from iaudit_backend.safe_log import log_event

from .state import RunState

STAGES = ("prep", "atomize", "link", "check")


def summarize(st: RunState, internal: InternalAudit, assemble_ms: int, total_ms: int) -> dict:
    """JSON-able and text-free. Span = first call start to last call end within the stage."""
    out: dict = {
        f"{s}_ms": round((st.spans[s][1] - st.spans[s][0]) * 1000) if s in st.spans else 0
        for s in STAGES
    }
    in_scope = [c for c in st.admitted.values() if c.scope == "in_scope"]
    stalled = sum(1 for d in internal.claims if d.outcome == "stalled")
    out.update(
        assemble_ms=assemble_ms,
        total_ms=total_ms,
        sections_ok=sum(1 for a in st.atoms.values() if a.status == "ok"),
        sections_failed=len(internal.section_failures),
        claims_in_scope=len(in_scope),
        claims_oos=len(st.admitted) - len(in_scope),
        claims_stalled=stalled,
        claims_ok=len(in_scope) - stalled,
        truncated=int(st.truncated),
        deadline_hit=int(st.deadline_hit),
        cancelled=st.cancelled,
    )
    return out


def log_audit_done(ctx, summary: dict) -> None:
    snap = ctx.metrics.snapshot()
    log_event(
        "audit_done",
        request_id=ctx.request_id,
        calls=snap["calls"],
        calls_ok=snap["ok"],
        **{k: v for k, v in summary.items() if k != "total_ms"},
        total_ms=summary["total_ms"],
    )
