"""Frozen v1.0.0 claim-to-sentence projection over saved audit responses.

Spans use Unicode code points and half-open section-0 intervals. Join spaces
belong to no sentence. Changing these rules requires a mapping version bump.
"""

from collections import Counter
from typing import Any

from iaudit_eval.datasets import Item

from .mapping import FrozenMapping, load_mapping

_INCONSISTENT = frozenset({"contradicted", "partially_supported", "insufficient_evidence"})


def project(
    response: dict[str, Any] | None, item: Item, mapping: FrozenMapping | None = None,
) -> dict[str, Any]:
    """Return text-free sentence labels and claim-level diagnostic counts.

    Union lists retain first-seen response order. Unknown concern counts include
    each name once per mapped claim, regardless of repeated concerns or the
    number of sentences the claim overlaps. Inputs are never modified.
    """
    if mapping is None:
        mapping = load_mapping()
    sources = item.payload["sentences"]
    assigned: list[list[dict[str, Any]]] = [[] for _ in sources]
    boundaries = [False for _ in sources]
    claims = response["claims"] if response is not None else []
    unmapped = 0
    crossing = 0
    unknown: Counter[str] = Counter()

    for claim in claims:
        span = claim["span"]
        start, end = span["start"]["char"], span["end"]["char"]
        overlaps = []
        if span["start"]["index"] == 0 and start < end:
            overlaps = [
                index for index, sentence in enumerate(sources)
                if max(start, sentence["start"]) < min(end, sentence["end"])
            ]
        if not overlaps:
            unmapped += 1
            continue
        boundary = len(overlaps) > 1
        crossing += int(boundary)
        unknown.update(
            {concern["type"] for concern in claim["concerns"]} - mapping.mapped_concerns
        )
        for index in overlaps:
            assigned[index].append(claim)
            boundaries[index] |= boundary

    sentences = []
    for source, mapped, boundary in zip(sources, assigned, boundaries, strict=True):
        verdicts = list(dict.fromkeys(claim["verdict"] for claim in mapped))
        meta = bool(mapped) and all(verdict == "out_of_scope" for verdict in verdicts)
        if _INCONSISTENT.intersection(verdicts):
            label = "inconsistent"
        elif not mapped:
            label = "unresolved"
        else:
            label = "consistent"
        sentences.append({
            "sent_idx": source["sent_idx"], "label": label, "meta": meta,
            "claim_ids": list(dict.fromkeys(claim["id"] for claim in mapped)),
            "verdicts": verdicts,
            "concerns": list(dict.fromkeys(
                concern["type"] for claim in mapped for concern in claim["concerns"]
            )),
            "boundary": boundary,
        })

    labels = {sentence["label"] for sentence in sentences}
    if "inconsistent" in labels:
        summary = "inconsistent"
    elif response is None or "unresolved" in labels:
        summary = "unresolved"
    else:
        summary = "consistent"
    return {
        "sentences": sentences, "summary": summary,
        "claims_total": len(claims), "claims_unmapped": unmapped,
        "claims_boundary_crossing": crossing,
        "concern_not_in_mapping": dict(sorted(unknown.items())),
    }
