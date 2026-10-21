"""Pure B3 comparisons over native gold and frozen sentence projections.

Concern levels use EI, MR, TAM, OF and CO; recall flags additionally use NMS
and RE. Concern pairs always have gold=True (desired agreement), with
``concern_population`` separating gold-inconsistent recall from gold-consistent
base rates. Only native sentence/summary levels carry diagnostic counts, so
alternate-policy and concern comparisons cannot multiply those counts.
"""

from copy import deepcopy
from typing import Any

from iaudit_eval.datasets import Item
from iaudit_eval.metrics.pair import Pair

from .mapping import FrozenMapping, load_mapping, normalize_type

TYPE_CODES = {
    "Extrinsic Information": "EI",
    "Mis-Referencing": "MR",
    "Tense/Modality": "TAM",
    "Stating Opinion as Fact": "OF",
    "Contradiction": "CO",
    "Nuanced Meaning Shift": "NMS",
    "Reasoning Error": "RE",
}


def pairs(
    item: Item,
    gold: dict[str, Any],
    prediction: dict[str, Any] | None,
    failure: str | None,
    mapping: FrozenMapping | None = None,
) -> list[Pair]:
    """Emit snapshot pairs without retaining gold text or explanations.

    A missing prediction or item-level failure makes every sentence unresolved.
    Failure reasons become ``unresolved`` here so B3's dual policies apply to
    every native/alternate unit and every applicable concern population.
    Sentence units are decimal sent_idx strings; summary units are empty.
    """
    mapping = mapping if mapping is not None else load_mapping()
    base = deepcopy(dict(item.meta))
    group = base["model_group"]
    dataset = base["dataset"]
    base.update({
        "group_dataset": f"{group}|{dataset}",
        "group_topic": f"{group}|{dataset}|{base['topic_category']}",
        "group_model": f"{group}|{base['model_name']}",
    })
    failed = prediction is None or failure is not None
    projected = {} if failed else {s["sent_idx"]: s for s in prediction["sentences"]}
    output = []
    alternate_labels = []

    def emit(level, unit, target, label, meta):
        unresolved = label is None or label == "unresolved"
        output.append(Pair(
            item.id, item.doc_id, level, unit, target,
            None if unresolved else label, "unresolved" if unresolved else None,
            deepcopy(meta),
        ))

    for source in gold["sentences"]:
        index = source["sent_idx"]
        sentence = projected.get(index)
        label = sentence["label"] if sentence is not None else "unresolved"
        is_meta = bool(sentence and sentence["meta"])
        alternate = "unresolved" if is_meta else label
        alternate_labels.append(alternate)
        for name in source["types"]:
            mapping.applicable_allowed(name, dataset)  # unknown type raises, as in item_rows
        types = {normalize_type(name) for name in source["types"]}
        meta = {
            **base, "sent_idx": index, "meta": is_meta,
            **{f"type_{code}": name in types for name, code in TYPE_CODES.items()},
        }
        emit("sentence", str(index), source["label"], label, {
            **meta,
            "claims_mapped": len(sentence["claim_ids"]) if sentence else 0,
            "meta_consistent_n": int(is_meta),
            "boundary_crossing_n": int(bool(sentence and sentence["boundary"])),
        })
        emit("sentence_meta_unresolved", str(index), source["label"], alternate, meta)
        inconsistent = source["label"] == "inconsistent"
        concern_meta = {
            **meta,
            "concern_population": "gold_inconsistent" if inconsistent else "gold_consistent",
        }
        concerns = sentence["concerns"] if sentence else ()
        for name, code in TYPE_CODES.items():
            if mapping.applicable_allowed(name, dataset) is None:
                continue
            if inconsistent and name not in types:
                continue
            match = None if label == "unresolved" else mapping.matches(name, dataset, concerns)
            emit(f"concern:{code}", str(index), True, match, concern_meta)
            if inconsistent and label == "inconsistent":
                emit(f"concern_detected:{code}", str(index), True, match, concern_meta)

    summary_meta = {**base, "sentences_total": len(gold["sentences"])}
    for key in ("claims_total", "claims_unmapped", "claims_boundary_crossing"):
        summary_meta[key] = 0 if failed else prediction[key]
    if not failed:
        summary_meta.update({
            f"concern_not_in_mapping:{name}": count
            for name, count in prediction["concern_not_in_mapping"].items()
        })
    summary = "unresolved" if failed else prediction["summary"]
    emit("summary", "", gold["summary"], summary, summary_meta)
    if "inconsistent" in alternate_labels:
        alternate_summary = "inconsistent"
    elif failed or "unresolved" in alternate_labels:
        alternate_summary = "unresolved"
    else:
        alternate_summary = "consistent"
    emit("summary_meta_unresolved", "", gold["summary"], alternate_summary, base)
    return output
