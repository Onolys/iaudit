"""AC3: no collection query in the repo layer lacks a uid filter (source-level check)."""

import ast
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[1] / "src/onolys_api/repo"
QUERY_CALLS = {"where", "order_by", "stream", "limit", "list_documents", "collection_group"}
# Helpers whose body establishes the uid scope; any other function that queries must call one.
SCOPE_HELPERS = {"_uid_query", "_owned_session", "_session_ref", "_owned_status"}
# Auth bootstrap: looks a key up by its id before the uid is known (documented in base.py).
UNSCOPED_ALLOWED = {"get_api_key", "_uid_query", "_owned_session"}


def _functions(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            yield node


def _called_names(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            yield f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


@pytest.mark.parametrize("fname", ["firestore.py"])
def test_every_query_function_is_uid_scoped(fname):
    tree = ast.parse((REPO_DIR / fname).read_text())
    offenders = []
    for fn in _functions(tree):
        names = set(_called_names(fn))
        if (names & QUERY_CALLS) and fn.name not in UNSCOPED_ALLOWED:
            if not (names & SCOPE_HELPERS):
                offenders.append(fn.name)
    assert offenders == [], f"queries without a uid scope: {offenders}"


def test_uid_query_helper_filters_on_uid_field():
    src = (REPO_DIR / "firestore.py").read_text()
    tree = ast.parse(src)
    helper = next(f for f in _functions(tree) if f.name == "_uid_query")
    assert '"uid"' in ast.get_source_segment(src, helper)


def _top_level_collection_calls(fn):
    """`self._client.collection(...)`: a top-level collection (subcollections hang off a session ref)."""
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("collection", "collection_group")
            and isinstance(n.func.value, ast.Attribute)
            and n.func.value.attr == "_client"
        ):
            yield n


def test_top_level_collections_only_via_uid_query_or_by_id_helpers():
    tree = ast.parse((REPO_DIR / "firestore.py").read_text())
    by_id_helpers = {"_top", "get_api_key"}  # document addressed by id; ownership checked after
    bad = [
        fn.name
        for fn in _functions(tree)
        if list(_top_level_collection_calls(fn))
        and "_uid_query" not in set(_called_names(fn))
        and fn.name not in by_id_helpers
    ]
    assert bad == [], f"top-level collection used without _uid_query: {bad}"
