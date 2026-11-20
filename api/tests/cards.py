"""A valid synthetic SP02 rating card (canonical `rating.schema.json` shape) for api tests."""

import copy

_CARD = {
    "change_goal": "Reduce evening drinking",
    "coded_span": {"from_s": 0, "to_s": 600},
    "globals": {
        "cct": {
            "score": 3,
            "reason": "The clinician asked what made walking important.",
            "example": {"at_s": 12, "text": "What makes walking more important to you?"},
        },
        "partnership": {"score": 4, "reason": "The clinician asked permission before ideas."},
    },
    "counts": {"question": {"count": 6, "note": None}, "sr": {"count": 4}},
    "notes": "Synthetic card for tests.",
}


def valid_card(**overrides) -> dict:
    """A fresh valid card (final-valid); keyword overrides replace top-level keys."""
    return {**copy.deepcopy(_CARD), **overrides}
