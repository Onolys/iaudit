"""Native TofuEval gold labels for on-demand, in-memory review.

Sentence text and explanations come only from the local item payload. Consumers
must omit those fields from run files, item rows, and metrics.
"""

from typing import Any

from iaudit_eval.datasets import Item


def gold(item: Item) -> dict[str, Any]:
    """Normalize raw yes/no annotations without modifying the source item.

    Preserve the C1 sentence order, code-point offsets, multi-label types, and
    verbatim text/explanations. A summary is inconsistent if any sentence is.
    Unknown raw labels are errors rather than inferred annotations.
    """
    sentences = []
    for source in item.payload["sentences"]:
        raw_label = source["label"]
        if raw_label not in ("yes", "no"):
            raise ValueError(f"Invalid TofuEval label at sentence {source['sent_idx']}")
        sentences.append(
            {
                "sent_idx": source["sent_idx"],
                "text": source["text"],
                "label": "consistent" if raw_label == "yes" else "inconsistent",
                "types": list(source["types"]),
                "exp": source["exp"],
                "start": source["start"],
                "end": source["end"],
            }
        )
    return {
        "sentences": sentences,
        "summary": (
            "inconsistent"
            if any(sentence["label"] == "inconsistent" for sentence in sentences)
            else "consistent"
        ),
    }
