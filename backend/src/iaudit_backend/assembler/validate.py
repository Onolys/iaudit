"""R7: independent rule check plus schema validation, quarantining bad claims once."""

import logging
from dataclasses import dataclass

from iaudit_backend.contract import validate_response
from iaudit_backend.models import AuditRequest

from .bounds import span_in_bounds
from .models import AssembleReport, AssemblyError

log = logging.getLogger("iaudit")
QUARANTINE_WARNING = "A claim failed final validation and was omitted."


@dataclass(frozen=True)
class Problem:
    claim: int | None  # index into response["claims"]; None = not attributable to one claim
    kind: str


def _claim_problems(claim: dict, turn_lens: list[int], sec_lens: list[int]) -> list[str]:
    out: list[str] = []
    if not span_in_bounds(claim["span"], sec_lens, single_index=True):
        out.append("rule1_claim_span")
    ids: set[str] = set()
    for e in claim["evidence"]:
        if not span_in_bounds(e["span"], turn_lens):
            out.append("rule1_evidence_span")
        if e["id"] in ids:
            out.append("rule7_duplicate_evidence_id")
        ids.add(e["id"])
    for c in claim["concerns"]:
        if any(i not in ids for i in c["evidence_ids"]):
            out.append("rule7_foreign_evidence_id")
    return out


def check_rules(request: AuditRequest, response: dict) -> list[Problem]:
    """Re-verify rules 1, 7, 8 and 10 from the final dict, without trusting earlier stages."""
    turn_lens = [len(t.text) for t in request.transcript]
    sec_lens = [len(s.text) for s in request.assessment]
    problems: list[Problem] = []
    if response.get("request_id") != request.request_id:
        problems.append(Problem(None, "rule10_request_id"))
    seen_ids: set[str] = set()
    valid: list[tuple[int, int, int, int]] = []  # (claim idx, section, start, end)
    for i, claim in enumerate(response.get("claims", [])):
        try:
            kinds = _claim_problems(claim, turn_lens, sec_lens)
            cid = claim["id"]
            if cid in seen_ids:
                kinds.append("rule7_duplicate_claim_id")
            seen_ids.add(cid)
            s, e = claim["span"]["start"], claim["span"]["end"]
            if not kinds:
                valid.append((i, s["index"], s["char"], e["char"]))
        except (KeyError, TypeError):
            kinds = ["malformed"]
        problems += [Problem(i, k) for k in kinds]
    for a in range(len(valid)):
        for b in range(a + 1, len(valid)):
            (ia, sa, xa, ya), (ib, sb, xb, yb) = valid[a], valid[b]
            if sa == sb and xa < yb and xb < ya:
                problems.append(Problem(max(ia, ib), "rule8_overlap"))
    return problems


def _claim_index(path: str) -> int | None:
    parts = path.split("/")
    if len(parts) >= 2 and parts[0] == "claims" and parts[1].isdigit():
        return int(parts[1])
    return None


def _find(request: AuditRequest, response: dict) -> tuple[set[int], bool]:
    """Return (bad claim indexes, has a problem outside any claim)."""
    bad: set[int] = set()
    outside = False
    for issue in validate_response(response, limit=None):
        log.warning("assembly_invalid path=%s keyword=%s", issue.path, issue.message)
        idx = _claim_index(issue.path)
        if idx is None:
            outside = True
        else:
            bad.add(idx)
    for p in check_rules(request, response):
        log.warning("assembly_invalid rule=%s", p.kind)
        if p.claim is None:
            outside = True
        else:
            bad.add(p.claim)
    return bad, outside


def finalize(request: AuditRequest, response: dict, report: AssembleReport | None = None) -> dict:
    bad, outside = _find(request, response)
    if outside:
        raise AssemblyError("response failed final validation")
    if bad:
        kept, dropped = [], []
        for i, c in enumerate(response["claims"]):
            (dropped if i in bad else kept).append(c)
        response["claims"] = kept
        for c in dropped:
            w = {"code": "other", "message": QUARANTINE_WARNING}
            if isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"]:
                w["claim_id"] = c["id"]
            response["warnings"].append(w)
            if report is not None:
                report.drop("claim_quarantined")
        bad, outside = _find(request, response)
        if bad or outside:
            raise AssemblyError("response failed final validation after quarantine")
    return response
