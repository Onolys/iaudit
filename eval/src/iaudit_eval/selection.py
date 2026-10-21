"""Reproducible item-level sampling."""

import random
from collections.abc import Sequence

from iaudit_eval.datasets.base import Item


def select(items: Sequence[Item], n: int | None, seed: int = 0) -> list[Item]:
    """Sort by id, seeded sample of n, return sorted by id. n=None or n>=len returns all."""
    ordered = sorted(items, key=lambda i: i.id)
    if n is None or n >= len(ordered):
        return ordered
    return sorted(random.Random(seed).sample(ordered, n), key=lambda i: i.id)
