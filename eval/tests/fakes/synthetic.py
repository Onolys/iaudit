"""Stable synthetic subset for engine tests with hand-calculated counts and metrics.

Taxonomy coverage uses the full public dataset in test_synthetic_dataset. These
fixtures retain three conversation clusters so control-flow tests do not start
running bootstrap statistics when new evaluation examples are added.
"""

from dataclasses import replace
from pathlib import Path

from iaudit_eval.datasets import load

ENGINE_DOC_IDS = {"doc-garden", "doc-physio", "doc-sleep"}


def engine_dataset():
    dataset = load("synthetic")

    class SubsetAdapter:
        def items(self, split):
            return [it for it in dataset.adapter.items(split) if it.doc_id in ENGINE_DOC_IDS]

        def __getattr__(self, name):
            return getattr(dataset.adapter, name)

    return replace(dataset, adapter=SubsetAdapter())


def restrict_engine_fixture(directory: Path):
    """Restrict a test's copied adapter, leaving the public dataset untouched."""
    adapter = directory / "eaudit/synthetic/adapter.py"
    adapter.write_text(
        adapter.read_text() + f"\n_DOCS = {{k: v for k, v in _DOCS.items() if k in {ENGINE_DOC_IDS!r}}}\n"
    )
