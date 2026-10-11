"""Pure-code synthesis: turn the verifier's observations into signals, roles and a verdict."""

from iaudit_backend.atomize.models import AtomicClaim

from .models import FlagObs, JudgedEvidence

# --- timeframe (bucket 4) -------------------------------------------------------------------


def timeframe_mismatch(claim_tf: str, item_tf: str) -> bool:
    if claim_tf == "unspecified" or item_tf == "unspecified":
        return False
    if item_tf == "hypothetical":
        return claim_tf != "hypothetical"
    if claim_tf in ("current", "future"):
        return item_tf in ("past", "childhood")
    if claim_tf in ("past", "childhood"):
        return item_tf == "current"
    return False


def apply_timeframe(claim: AtomicClaim, items: list[JudgedEvidence], flags: list[FlagObs]) -> int:
    """Demote items from the wrong period: they no longer count as support or contradiction.

    An implicit-current claim (the text never states a time) only fires at high confidence.
    Returns the number of demoted items.
    """
    implicit = claim.timeframe == "current" and not claim.timeframe_explicit
    flagged = {
        k
        for f in flags
        if f.type == "timeframe_mismatch" and (not implicit or f.conf == "high")
        for k in f.keys
    }
    n = 0
    for it in items:
        o = it.obs
        if o is None or o.relation == "not_addresses" or it.demote:
            continue
        hit = timeframe_mismatch(claim.timeframe, o.timeframe) and (
            not implicit or o.conf == "high"
        )
        if hit or it.key in flagged:
            it.demote = "timeframe"
            n += 1
    return n
