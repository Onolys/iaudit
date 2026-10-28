"""The public taxonomy is complete and its type/group relationship is enforced."""

import copy
import json
from pathlib import Path

import pytest

from eaudit import contract


def test_group_map_matches_schema():
    from eaudit.models import ConcernType
    from eaudit.models.concern_groups import GROUP_OF

    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/audit-response.schema.json").read_text())
    concern = schema["$defs"]["Concern"]
    assert list(ConcernType) == concern["properties"]["type"]["enum"]
    assert len(GROUP_OF) == 17
    clauses = concern["allOf"]
    assert len(clauses) == 4
    schema_map = {
        kind: clause["then"]["properties"]["group"]["const"]
        for clause in clauses
        for kind in clause["if"]["properties"]["type"]["enum"]
    }
    assert GROUP_OF == schema_map
    assert set(GROUP_OF.values()) == set(concern["properties"]["group"]["enum"])


def test_concern_requires_group(example_response):
    bad = copy.deepcopy(example_response)
    concern = next(c for claim in bad["claims"] for c in claim["concerns"])
    concern.pop("group", None)
    assert contract.validate_response(bad)


@pytest.mark.parametrize(("kind", "group"), [
    ("unsupported_claim", "changed_detail"),
    ("contradictory_evidence", "missing_context"),
    ("opinion_as_fact", "not_in_interview"),
    ("context_stripping", "opposite_of_interview"),
    ("unknown_concern", "changed_detail"),
])
def test_schema_rejects_inconsistent_or_unknown_concern(example_response, kind, group):
    concern = next(c for claim in example_response["claims"] for c in claim["concerns"])
    concern.update(type=kind, group=group)
    assert contract.validate_response(example_response)


@pytest.mark.parametrize("kind", ["opinion_as_fact", "calculation_error", "meaning_shift", "unsupported_inference"])
def test_new_concern_types_are_accepted(example_response, kind):
    from eaudit.models.concern_groups import GROUP_OF

    concern = next(c for claim in example_response["claims"] for c in claim["concerns"])
    concern.update(type=kind, group=GROUP_OF[kind])
    assert contract.validate_response(example_response) == []


@pytest.mark.parametrize("kind", ["opinion_as_fact", "calculation_error", "meaning_shift", "unsupported_inference"])
def test_assembler_derives_group(example_request, kind):
    from eaudit.assembler import ClaimDraft, ConcernDraft, InternalAudit, assemble
    from eaudit.config import Settings
    from eaudit.models import AuditRequest
    from eaudit.models.concern_groups import GROUP_OF

    request = AuditRequest.model_validate(example_request)
    draft = ClaimDraft(
        key="new-type", section_index=0,
        segments=[request.assessment[0].text], verdict="insufficient_evidence",
        explanation="Review the supplied evidence.",
        concerns=[ConcernDraft(type=kind, explanation="Review this discrepancy.")],
    )
    response = assemble(request, InternalAudit(claims=[draft]), Settings()).response
    assert contract.validate_response(response) == []
    assert response["claims"][0]["concerns"][0]["group"] == GROUP_OF[kind]
