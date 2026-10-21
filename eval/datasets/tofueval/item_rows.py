"""Text-free, deterministic gold-versus-prediction rows for TofuEval review.

Unresolved outcomes stay explicit in the UI; the primary scoring policy counts
those units wrong. Native gold type spellings are preserved in all display data.
"""

from typing import Any

from iaudit_eval.datasets import Item
from iaudit_eval.metrics.report import ItemRow

from .mapping import FrozenMapping, load_mapping


def _outcome(gold: str, prediction: str) -> str:
    if prediction == "unresolved":
        return "unresolved"
    if gold == "inconsistent":
        return "tp" if prediction == "inconsistent" else "fn"
    return "fp" if prediction == "inconsistent" else "tn"


def build(
    item: Item,
    gold: dict[str, Any],
    prediction: dict[str, Any] | None,
    failure: str | None,
    mapping: FrozenMapping | None = None,
) -> ItemRow:
    """Build a detached B3 row, allowing only the PRD's display fields.

    Missing predictions and item failures expose no claim predictions. Sentence
    joins use sent_idx rather than list position. Only applicable scored gold
    types receive concern matches; recall-only types remain in gold_types.
    """
    mapping = mapping if mapping is not None else load_mapping()
    failed = prediction is None or failure is not None
    projected = {} if failed else {s["sent_idx"]: s for s in prediction["sentences"]}
    sentences = []
    dataset = item.meta["dataset"]
    for source in gold["sentences"]:
        predicted = projected.get(source["sent_idx"])
        label = predicted["label"] if predicted is not None else "unresolved"
        concerns = list(predicted["concerns"]) if predicted is not None else []
        sentences.append({
            "sent_idx": source["sent_idx"], "start": source["start"], "end": source["end"],
            "gold_label": source["label"], "gold_types": list(source["types"]),
            "pred_label": label, "meta": bool(predicted and predicted["meta"]),
            "claim_ids": list(predicted["claim_ids"]) if predicted is not None else [],
            "verdicts": list(predicted["verdicts"]) if predicted is not None else [],
            "concerns": concerns, "outcome": _outcome(source["label"], label),
            "concern_match": {
                name: label != "unresolved" and mapping.matches(name, dataset, concerns)
                for name in source["types"]
                if mapping.applicable_allowed(name, dataset) is not None
            },
        })

    count = len(sentences)
    gold_count = sum(s["gold_label"] == "inconsistent" for s in sentences)
    pred_count = sum(s["pred_label"] == "inconsistent" for s in sentences)
    unresolved = sum(s["pred_label"] == "unresolved" for s in sentences)
    summary = "unresolved" if failed else prediction["summary"]
    outcome = _outcome(gold["summary"], summary)
    status = "unmapped" if failure == "unmapped" else "failed" if failed else "ok"
    return ItemRow(
        item_id=item.id,
        label=f"{item.doc_id} / {item.meta['topic']} / {item.meta['model_name']}",
        status=status,
        gold=f"{gold['summary']} ({gold_count} of {count} sentences)",
        pred=f"{summary} ({pred_count} of {count}; {unresolved} unresolved)",
        match=None if outcome == "unresolved" else outcome in {"tp", "tn"},
        outcome=outcome,
        detail={
            "doc_id": item.doc_id, "dataset": dataset,
            "topic_category": item.meta["topic_category"],
            "model_name": item.meta["model_name"], "model_group": item.meta["model_group"],
            "gold": {
                "summary": gold["summary"], "n_sentences": count,
                "n_inconsistent": gold_count,
                "types": list(dict.fromkeys(
                    name for source in gold["sentences"] for name in source["types"]
                )),
            },
            "pred": {
                "summary": summary, "n_inconsistent": pred_count,
                "n_unresolved": unresolved, "n_meta": sum(s["meta"] for s in sentences),
            },
            "sentences": sentences,
        },
    )
