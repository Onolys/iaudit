"""Hand-computed projection cases over fictional code-point spans; entirely offline."""

import importlib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from iaudit_eval.datasets import Item

EVAL = Path(__file__).resolve().parents[2]


def project(response, item, monkeypatch, mapping=None):
    path = EVAL / "datasets/tofueval/projection.py"
    assert path.is_file(), "TofuEval claim projection is not implemented"
    monkeypatch.syspath_prepend(str(EVAL))
    module = importlib.import_module("datasets.tofueval.projection")
    return module.project(response, item, mapping)


def item():
    # Assessment is "Café. 紙の鳥。 Fin."; join spaces at 5 and 10 belong to no sentence.
    return Item(
        id="fictional-projection", doc_id="fictional-doc", split="dev",
        meta={"dataset": "mediasum"},
        payload={"sentences": [
            {"sent_idx": 1, "text": "Café.", "label": "yes", "types": [], "exp": "",
             "start": 0, "end": 5},
            {"sent_idx": 9, "text": "紙の鳥。", "label": "yes", "types": [], "exp": "",
             "start": 6, "end": 10},
            {"sent_idx": 10, "text": "Fin.", "label": "yes", "types": [], "exp": "",
             "start": 11, "end": 15},
        ]},
    )


def claim(start=0, end=5, verdict="supported", *, cid="c1", section=0, concerns=()):
    evidence = []
    if verdict in {"supported", "contradicted"}:
        evidence = [{"id": "e1", "role": "supporting" if verdict == "supported" else "contradicting",
                     "span": {"start": {"index": 0, "char": 0}, "end": {"index": 0, "char": 1}}}]
    result = {
        "id": cid, "span": {"start": {"index": section, "char": start},
                              "end": {"index": section, "char": end}},
        "verdict": verdict, "explanation": "Fictional audit explanation.",
        "concerns": [{"type": name, "explanation": "Fictional concern.", "evidence_ids": []}
                     for name in concerns],
        "evidence": evidence,
    }
    if verdict == "out_of_scope":
        result["out_of_scope_reason"] = "Fictional inference requiring external criteria."
    return result


def response(*claims, status="complete"):
    return {"schema_version": "1.2.0", "status": status,
            "warnings": ([{"code": "section_not_processed", "message": "Fictional omission.",
                           "section_index": 0}] if status == "partial" else []),
            "claims": list(claims)}


@pytest.mark.parametrize(
    "start,end,section,ids,boundary,unmapped",
    [
        (3, 4, 0, [["c1"], [], []], False, 0),  # é counts as one code point.
        (4, 7, 0, [["c1"], ["c1"], []], True, 0),  # one point in each neighbour
        (0, 15, 0, [["c1"], ["c1"], ["c1"]], True, 0),
        (5, 6, 0, [[], [], []], False, 1),  # join space only
        (0, 5, 1, [[], [], []], False, 1),
        (2, 2, 0, [[], [], []], False, 1),
        (20, 21, 0, [[], [], []], False, 1),
        (0, 5, 0, [["c1"], [], []], False, 0),  # half-open excludes join
        (5, 7, 0, [[], ["c1"], []], False, 0),  # end at first point of s9
        (10, 11, 0, [[], [], []], False, 1),
    ],
)
def test_half_open_spans_assign_every_overlapped_sentence(
    monkeypatch, start, end, section, ids, boundary, unmapped,
):
    result = project(response(claim(start, end, section=section)), item(), monkeypatch)
    assert [sentence["claim_ids"] for sentence in result["sentences"]] == ids
    assert [sentence["boundary"] for sentence in result["sentences"]] == [
        boundary and bool(sentence_ids) for sentence_ids in ids
    ]
    assert result["claims_total"] == 1
    assert result["claims_unmapped"] == unmapped
    # A three-sentence claim is still one boundary-crossing claim.
    assert result["claims_boundary_crossing"] == int(boundary)


@pytest.mark.parametrize(
    "verdicts,label,meta",
    [
        ([], "unresolved", False),
        (["supported"], "consistent", False),
        (["supported", "out_of_scope"], "consistent", False),
        (["out_of_scope", "supported"], "consistent", False),
        (["out_of_scope", "out_of_scope"], "consistent", True),
        (["supported", "contradicted"], "inconsistent", False),
        (["out_of_scope", "partially_supported"], "inconsistent", False),
        (["insufficient_evidence", "supported"], "inconsistent", False),
    ],
)
def test_sentence_rules_first_match_and_meta_mix(monkeypatch, verdicts, label, meta):
    claims = [claim(index, index + 1, verdict, cid=f"c{index}",
                    concerns=("unsupported_claim",) if verdict == "partially_supported" else ())
              for index, verdict in enumerate(verdicts)]
    result = project(response(*claims), item(), monkeypatch)
    first = result["sentences"][0]
    assert (first["label"], first["meta"]) == (label, meta)
    assert first["verdicts"] == list(dict.fromkeys(verdicts))


@pytest.mark.parametrize(
    "claims,expected",
    [
        ([], "unresolved"),
        ([claim(0, 5)], "unresolved"),
        ([claim(0, 5, "contradicted")], "inconsistent"),
        ([claim(0, 15)], "consistent"),
        ([claim(0, 15, "out_of_scope")], "consistent"),
    ],
)
def test_summary_precedence(monkeypatch, claims, expected):
    assert project(response(*claims), item(), monkeypatch)["summary"] == expected


@pytest.mark.parametrize("saved", [None, response(status="partial"), response()])
def test_failed_or_empty_response_is_all_unresolved(monkeypatch, saved):
    result = project(saved, item(), monkeypatch)
    assert result == {
        "sentences": [
            {"sent_idx": 1, "label": "unresolved", "meta": False, "claim_ids": [],
             "verdicts": [], "concerns": [], "boundary": False},
            {"sent_idx": 9, "label": "unresolved", "meta": False, "claim_ids": [],
             "verdicts": [], "concerns": [], "boundary": False},
            {"sent_idx": 10, "label": "unresolved", "meta": False, "claim_ids": [],
             "verdicts": [], "concerns": [], "boundary": False},
        ], "summary": "unresolved", "claims_total": 0, "claims_unmapped": 0,
        "claims_boundary_crossing": 0, "concern_not_in_mapping": {},
    }


def test_union_order_is_first_seen_and_unknown_diagnostics_count_claims(monkeypatch):
    saved = response(
        claim(4, 7, "partially_supported", cid="z", concerns=(
            "unsupported_claim", "context_stripping", "quantity_mismatch", "context_stripping",
        )),
        claim(7, 8, "insufficient_evidence", cid="a", concerns=(
            "quantity_mismatch", "certainty_inflation",
        )),
        claim(10, 11, "insufficient_evidence", cid="unmapped", concerns=("quantity_mismatch",)),
    )
    result = project(saved, item(), monkeypatch)
    assert result["sentences"][1] == {
        "sent_idx": 9, "label": "inconsistent", "meta": False, "claim_ids": ["z", "a"],
        "verdicts": ["partially_supported", "insufficient_evidence"],
        "concerns": ["unsupported_claim", "context_stripping", "quantity_mismatch", "certainty_inflation"],
        "boundary": True,
    }
    # Crossing contributes once, repeats within a claim once, unmapped contributes zero.
    assert result["concern_not_in_mapping"] == {"context_stripping": 1, "quantity_mismatch": 2}
    assert result["claims_total"] == 3
    assert result["claims_unmapped"] == 1
    assert result["claims_boundary_crossing"] == 1


def test_supplied_mapping_controls_unknown_counts_without_changing_labels(monkeypatch):
    monkeypatch.syspath_prepend(str(EVAL))
    mapping = importlib.import_module("datasets.tofueval.mapping").load_mapping()
    mapping = replace(mapping, mapped_concerns=mapping.mapped_concerns | {"quantity_mismatch"})
    result = project(response(claim(concerns=("quantity_mismatch",))), item(), monkeypatch, mapping)
    assert result["concern_not_in_mapping"] == {}
    assert result["sentences"][0]["label"] == "consistent"


def test_projection_does_not_mutate_or_alias_inputs_and_keeps_no_text(monkeypatch):
    source = item()
    saved = response(claim(concerns=("unsupported_claim",)))
    original = deepcopy((source, saved))
    result = project(saved, source, monkeypatch)
    assert (source, saved) == original
    assert "text" not in str(result) and "explanation" not in str(result)
    result["sentences"][0]["claim_ids"].append("changed")
    result["sentences"][0]["concerns"].append("changed")
    assert (source, saved) == original
