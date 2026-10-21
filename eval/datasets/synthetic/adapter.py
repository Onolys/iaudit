"""Synthetic fictional dataset: 3 conversations, 8 items, one label per item.

Everything here is invented. Gold is the item label ("clean" or "flagged");
project() maps an AuditResponse onto the same labels.
"""

from __future__ import annotations

from iaudit_eval.datasets import Item, Unmapped
from iaudit_eval.metrics.pair import Pair, default_pairs

_SCHEMA_VERSION = "1.1.0"
_FLAGGING = {"contradicted", "partially_supported", "insufficient_evidence"}
_NEUTRAL = {"supported", "out_of_scope"}

_DOCS = {
    "doc-garden": {
        "split": "dev",
        "topic": "meeting",
        "turns": [
            ("rowan_k", "interviewer", "Let us settle the plot rota for the spring season."),
            ("mira_t", "respondent", "I can water the beds on Tuesdays but not on weekends."),
            ("rowan_k", "interviewer", "Does anyone object to buying seed potatoes in bulk?"),
            ("pello_v", "respondent", "Bulk is fine if the club shed stays dry until planting."),
            ("mira_t", "respondent", "The shed roof leaked once in March, then Pello patched it."),
        ],
        "items": [
            ("garden-clean", "clean",
             "Mira offered to water the beds on Tuesdays. Pello agreed to bulk potatoes."),
            ("garden-weekend", "flagged",
             "Mira will water the beds every day of the week, including weekends."),
            ("garden-roof", "flagged",
             "The shed roof has leaked repeatedly and still has not been repaired."),
        ],
    },
    "doc-physio": {
        "split": "dev",
        "topic": "clinical",
        "turns": [
            ("physio_ines", "interviewer", "How has the left knee felt since the last visit?"),
            (
                "client_ola",
                "respondent",
                "Stairs are easier now, though the ache returns after long walks.",
            ),
            ("physio_ines", "interviewer", "Are you still doing the band exercises each morning?"),
            (
                "client_ola",
                "respondent",
                "Most mornings. I skipped them twice during the holiday week.",
            ),
        ],
        "items": [
            ("physio-clean", "clean",
             "Ola finds stairs easier. An ache returns after long walks."),
            ("physio-adherence", "flagged",
             "Ola never misses the band exercises and has done them every morning."),
            ("physio-pain", "flagged",
             "Ola reports the knee pain is completely gone, even after long walks."),
        ],
    },
    "doc-sleep": {
        "split": "test",
        "topic": "clinical",
        "turns": [
            ("nurse_pell", "interviewer", "Tell me about your nights over the past fortnight."),
            (
                "client_tavi",
                "respondent",
                "I fall asleep quickly but wake around four most nights.",
            ),
            ("nurse_pell", "interviewer", "Do you take anything to help with that?"),
            ("client_tavi", "respondent", "Only chamomile tea. I stopped coffee after lunch."),
        ],
        "items": [
            ("sleep-clean", "clean",
             "Tavi falls asleep quickly and often wakes near four. Chamomile tea is the only aid."),
            ("sleep-meds", "flagged",
             "Tavi relies on prescription sleeping tablets to get through the night."),
        ],
    },
}


class SyntheticAdapter:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    def items(self, split: str):
        out = []
        for doc_id, doc in _DOCS.items():
            if doc["split"] != split:
                continue
            for item_id, label, summary in doc["items"]:
                out.append(
                    Item(
                        id=item_id,
                        doc_id=doc_id,
                        split=split,
                        payload={"turns": [list(t) for t in doc["turns"]], "summary": summary,
                                 "label": label},
                        meta={"topic": doc["topic"]},
                    )
                )
        return out

    def to_request(self, item: Item) -> dict:
        p = item.payload
        return {
            "schema_version": _SCHEMA_VERSION,
            "request_id": item.id,
            "transcript": [
                {"id": f"t{k}", "speaker": s, "role": r, "text": x}
                for k, (s, r, x) in enumerate(p["turns"])
            ],
            "assessment": [{"id": "s0", "text": p["summary"]}],
        }

    def gold(self, item: Item) -> str:
        return item.payload["label"]

    def project(self, response: dict, item: Item) -> str:
        if not isinstance(response, dict):
            raise Unmapped("response is not an object")
        claims = response.get("claims")
        if response.get("status") != "complete" or not isinstance(claims, list) or not claims:
            raise Unmapped("response is not a complete audit with claims")
        verdicts = []
        for c in claims:
            v = c.get("verdict") if isinstance(c, dict) else None
            if v not in _FLAGGING and v not in _NEUTRAL:
                raise Unmapped("unrecognised claim verdict")
            verdicts.append(v)
        return "flagged" if any(v in _FLAGGING for v in verdicts) else "clean"

    def pairs(self, item: Item, gold, pred, failure) -> list[Pair]:
        """Two levels: the item label, and a boolean per assessment section (unit "s0").

        The synthetic assessment has one section, so the section pair restates the item label
        as flagged True/False; it exists to exercise the multi-level scoring path.
        """
        out = default_pairs(item, gold, pred, failure)
        out.append(
            Pair(item.id, item.doc_id, "section", "s0", gold == "flagged",
                 None if pred is None else pred == "flagged", failure, item.meta)
        )  # fmt: skip
        return out


def create(data_dir):
    return SyntheticAdapter(data_dir)
