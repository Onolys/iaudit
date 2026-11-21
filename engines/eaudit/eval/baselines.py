"""R13 (parked): the bucket-1 baseline hook. No baseline model is implemented.

Bucket 1 is "supported vs not supported". A baseline predicts that label from the claim text and
its evidence text. The registry names two candidates; both raise `BaselineNotInstalled` with an
install note, so heavy dependencies never enter the default environment.
"""

from collections.abc import Callable
from typing import Literal, Protocol

Label = Literal["supported", "not_supported"]


class BaselineNotInstalled(RuntimeError):
    pass


class Bucket1Baseline(Protocol):
    def predict(self, claim_text: str, evidence_text: str) -> Label: ...


def _missing(name: str, extra: str) -> Callable[[], Bucket1Baseline]:
    def make() -> Bucket1Baseline:
        raise BaselineNotInstalled(
            f"baseline {name!r} is not installed. It would live in an optional extra "
            f"({extra}) and is never part of the default environment."
        )

    return make


REGISTRY: dict[str, Callable[[], Bucket1Baseline]] = {
    "minicheck-flan-t5-l": _missing("minicheck-flan-t5-l", "uv sync --extra baselines"),
    "gpt-4o-mini": _missing("gpt-4o-mini", "uv sync --extra baselines, plus OPENAI_API_KEY"),
}


def get_baseline(name: str) -> Bucket1Baseline:
    if name not in REGISTRY:
        raise KeyError(f"unknown baseline {name!r}; known: {', '.join(sorted(REGISTRY))}")
    return REGISTRY[name]()


def run_baseline(baseline: Bucket1Baseline, inputs: list[tuple[str, str, str]]) -> dict:
    """`inputs` are (claim_text, evidence_text, gold_label) from the Gold-mode bucket-1 rows.

    Same report shape as the harness: counts, precision, recall, F1 for detecting
    `not_supported`, with the indicative-only flag at small n.
    """
    tp = fp = fn = 0
    for claim, evidence, gold in inputs:
        pred = baseline.predict(claim, evidence)
        tp += int(pred == "not_supported" and gold == "not_supported")
        fp += int(pred == "not_supported" and gold == "supported")
        fn += int(pred == "supported" and gold == "not_supported")
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    n = tp + fn
    return {
        "buckets": {"1": {"concern": "unsupported_claim", "tp": tp, "fp": fp, "fn": fn, "n": n,
                          "precision": p, "recall": r, "f1": f1,
                          "flags": ["indicative only (n < 5)"] if n < 5 else []}},
    }  # fmt: skip
