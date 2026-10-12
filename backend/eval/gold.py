"""Gold labels (07 R5): one JSONL file per fixture, one claim per line.

The loader is strict: an unknown field, verdict, concern, role or bucket name is an error, and
the label must satisfy contract rules 2-6 so a bad label cannot score a good pipeline down.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from eval.adhd import DATA
from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.models import ConcernType, EvidenceRole, Verdict
from iaudit_backend.scales import FrequencyBucket, SeverityBucket

GOLD_VERSION = 1
CONCERNS = [c.value for c in ConcernType]  # bucket = 1-based position (mission check number)
ROLES_IN_FIXTURE = {"target", "control", "cdr"}
PRIORITIES = {"P0", "P1", "stretch", "control"}
STATUSES = {"approved", "proposed"}
_TOP = {
    "gold_version", "fixture", "claim_id", "section_index", "claim_text", "start", "end",
    "role_in_fixture", "bucket", "priority", "verdict", "concerns_required", "concerns_allowed",
    "explanation_contains", "evidence", "expect_warnings", "slots", "status",
}  # fmt: skip
_EVIDENCE = {"turn", "role", "roles_ok", "required", "char_start", "char_end"}
_SLOTS = {
    "proposition", "scope", "oos_category", "subject_text", "subject_speaker", "reported_by",
    "polarity", "quantities", "timeframe", "timeframe_explicit", "hedged", "links",
}  # fmt: skip
_BUCKETS = {"frequency": FrequencyBucket, "severity": SeverityBucket}


class GoldError(ValueError):
    pass


@dataclass
class GoldEvidence:
    turn: int
    role: str
    roles_ok: list[str]
    required: bool = True
    char_start: int | None = None
    char_end: int | None = None


@dataclass
class GoldClaim:
    fixture: str
    claim_id: str
    section_index: int
    claim_text: str
    start: int
    end: int
    role_in_fixture: str
    bucket: int | None
    priority: str
    verdict: str
    concerns_required: list[str]
    concerns_allowed: list[str]
    explanation_contains: list[str]
    evidence: list[GoldEvidence]
    expect_warnings: list[str]
    slots: dict
    status: str
    extras: dict = field(default_factory=dict)

    @property
    def required_turns(self) -> list[int]:
        return sorted({e.turn for e in self.evidence if e.required})

    def atomic_claim(self, n: int) -> AtomicClaim:
        """The SP03 claim the Gold and Linked modes feed to link / check."""
        data = {k: v for k, v in self.slots.items() if k != "links"}
        return AtomicClaim.model_validate(
            {
                **data,
                "id": f"c{self.section_index}.{n}",
                "section_index": self.section_index,
                "segments": [self.claim_text],
                "span_hint": (self.start, self.end),
            }
        )


def _enum(value, allowed, what: str) -> None:
    if value not in allowed:
        raise GoldError(f"unknown {what}: {value!r}")


def _check_slots(slots: dict) -> None:
    extra = set(slots) - _SLOTS
    if extra:
        raise GoldError(f"unknown slot field(s): {sorted(extra)}")
    for q in slots.get("quantities", []):
        _enum(q.get("kind"), _BUCKETS, "quantity kind")
        if q.get("bucket") is not None:
            _enum(q["bucket"], _BUCKETS[q["kind"]].__members__, f"{q['kind']} bucket")


def _check_rules(c: GoldClaim) -> None:
    roles = {e.role for e in c.evidence}
    v = c.verdict
    if v == "supported" and ("supporting" not in roles or "contradicting" in roles):
        raise GoldError(f"{c.claim_id}: supported needs supporting and no contradicting evidence")
    if v == "contradicted" and "contradicting" not in roles:
        raise GoldError(f"{c.claim_id}: contradicted needs contradicting evidence")
    if v == "partially_supported" and not c.concerns_required:
        raise GoldError(f"{c.claim_id}: partially_supported needs a required concern")
    if v == "insufficient_evidence" and "contradicting" in roles:
        raise GoldError(f"{c.claim_id}: insufficient_evidence cannot cite contradicting evidence")
    if v == "out_of_scope" and (c.evidence or c.concerns_required):
        raise GoldError(f"{c.claim_id}: out_of_scope carries no evidence or concerns")


def parse_claim(row: dict, fixture: str | None = None) -> GoldClaim:
    extra = set(row) - _TOP
    if extra:
        raise GoldError(f"unknown field(s): {sorted(extra)}")
    if row.get("gold_version") != GOLD_VERSION:
        raise GoldError(f"gold_version must be {GOLD_VERSION}")
    _enum(row["verdict"], {v.value for v in Verdict}, "verdict")
    for key in ("concerns_required", "concerns_allowed"):
        for t in row[key]:
            _enum(t, CONCERNS, "concern")
    _enum(row["role_in_fixture"], ROLES_IN_FIXTURE, "role_in_fixture")
    _enum(row["priority"], PRIORITIES, "priority")
    _enum(row["status"], STATUSES, "status")
    if row["bucket"] is not None and not 1 <= row["bucket"] <= len(CONCERNS):
        raise GoldError(f"bucket out of range: {row['bucket']}")
    evidence = []
    for e in row["evidence"]:
        if set(e) - _EVIDENCE:
            raise GoldError(f"unknown evidence field(s): {sorted(set(e) - _EVIDENCE)}")
        _enum(e["role"], {r.value for r in EvidenceRole}, "evidence role")
        for r in e["roles_ok"]:
            _enum(r, {r.value for r in EvidenceRole}, "roles_ok role")
        evidence.append(GoldEvidence(**e))
    _check_slots(row["slots"])
    for w in row["expect_warnings"]:
        _enum(w, {"ambiguous_speaker", "section_not_processed", "input_truncated", "other"},
              "warning")  # fmt: skip
    claim = GoldClaim(
        fixture=row["fixture"], claim_id=row["claim_id"], section_index=row["section_index"],
        claim_text=row["claim_text"], start=row["start"], end=row["end"],
        role_in_fixture=row["role_in_fixture"], bucket=row["bucket"], priority=row["priority"],
        verdict=row["verdict"], concerns_required=row["concerns_required"],
        concerns_allowed=row["concerns_allowed"], explanation_contains=row["explanation_contains"],
        evidence=evidence, expect_warnings=row["expect_warnings"], slots=row["slots"],
        status=row["status"],
    )  # fmt: skip
    if fixture and claim.fixture != fixture:
        raise GoldError(f"{claim.claim_id}: fixture {claim.fixture!r} != {fixture!r}")
    _check_rules(claim)
    claim.atomic_claim(1)  # slots must be a valid SP03 claim
    return claim


def load_gold(fixture: str, root: Path = DATA) -> list[GoldClaim]:
    """`fixture` is the short name (`faithful`, `v1`, `v4-noroles`)."""
    path = Path(root) / "gold" / f"{fixture}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return [parse_claim(r, f"adhd-{fixture}") for r in rows]
