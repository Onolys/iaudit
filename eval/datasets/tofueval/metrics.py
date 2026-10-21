"""Native scalar diagnostics; classification formulas are the core B3 objects.

Diagnostic policies are ``none``: counts describe the saved projection, including
unresolved units. Sentence assignments count a crossing claim in each sentence;
claim-level rates and unknown concerns read summary totals once per item.
"""

from iaudit_eval.metrics import builtins
from iaudit_eval.metrics.pair import Result
from iaudit_eval.metrics.registry import pairwise


def claims_per_sentence(pairs):
    """Mapped claim assignments per native sentence; n is the sentence count."""
    n = len(pairs)
    return Result(sum(p.meta.get("claims_mapped", 0) for p in pairs) / n if n else None, n)


def claim_rate(pairs, *, key):
    """Claim-level diagnostic numerator / all claims, counted once per summary."""
    n = sum(p.meta.get("claims_total", 0) for p in pairs)
    count = sum(p.meta.get(key, 0) for p in pairs)
    return Result(count / n if n else None, n)


def meta_consistent_n(pairs):
    """Count native meta-consistent sentences; n is all native sentences."""
    return Result(sum(p.meta.get("meta_consistent_n", 0) for p in pairs), len(pairs))


def concern_not_in_mapping(pairs, *, key=None):
    """Count unmapped concern occurrences, including previously unseen names.

    n is mapped claims (the population that can carry these counts), and key
    optionally selects a flattened per-concern field. No claim text is retained.
    """
    n = sum(p.meta.get("claims_total", 0) - p.meta.get("claims_unmapped", 0) for p in pairs)
    count = sum(
        p.meta.get(key, 0) if key is not None else sum(
            value for name, value in p.meta.items() if name.startswith("concern_not_in_mapping:")
        )
        for p in pairs
    )
    return Result(count, n)


METRICS = {
    "balanced_accuracy": builtins.BalancedAccuracy,
    "precision": builtins.Precision,
    "recall": builtins.Recall,
    "f1": builtins.F1,
    "recall_by_type": builtins.RecallByType,
    "failure_rate": builtins.FailureRate,
    "claims_per_sentence": pairwise("claims_per_sentence", claims_per_sentence, policy="none"),
    "unmapped_claim_rate": pairwise("unmapped_claim_rate", claim_rate, policy="none"),
    "boundary_crossing_rate": pairwise("boundary_crossing_rate", claim_rate, policy="none"),
    "meta_consistent_n": pairwise("meta_consistent_n", meta_consistent_n, policy="none"),
    "concern_not_in_mapping": pairwise(
        "concern_not_in_mapping", concern_not_in_mapping, policy="none",
    ),
}
