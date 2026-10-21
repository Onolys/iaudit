"""Scoring and comparison stay offline and never modify protected project areas."""

import hashlib
import socket
from pathlib import Path

import pytest
from test_scoring import _make_run

from iaudit_eval.compare import compare
from iaudit_eval.scoring import score


@pytest.fixture
def saved_runs(tmp_path):
    # Build saved responses with the fake transport before exercising pure scoring.
    a = _make_run(tmp_path, on_finish=None)
    b = _make_run(tmp_path, "500", on_finish=None)
    return tmp_path, a, b


def test_score_and_compare_work_with_sockets_blocked(saved_runs, monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("scoring/comparison attempted network access")

    # Block both socket construction and DNS, including callers using convenience APIs.
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    root, a, b = saved_runs
    report = score(a, runs_root=root)
    comparison = compare(a, b, runs_root=root)
    assert report["items"] == {"selected": 8, "scored": 8, "failed": 0, "not_run": 0}
    assert (root / a / "metrics.json").is_file()
    assert comparison["n_shared"] == 8
    recall = next(
        d for d in comparison["deltas"]
        if (d["metric"], d["level"], d["policy"], d["slice"])
        == ("recall", "item", "primary", {})
    )
    assert recall["a"]["value"] == 1.0
    assert recall["b"]["value"] == 0.0
    assert recall["delta"] == -1.0


def _protected_files(repo):
    return {
        str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in (repo / "backend/eval", repo / "docs/contracts")
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_score_and_compare_leave_protected_areas_unchanged(saved_runs):
    repo = Path(__file__).resolve().parents[2]
    before = _protected_files(repo)
    assert any(path.startswith("backend/eval/") for path in before)
    assert any(path.startswith("docs/contracts/") for path in before)
    root, a, b = saved_runs
    score(a, runs_root=root)
    assert _protected_files(repo) == before
    compare(a, b, runs_root=root)
    assert _protected_files(repo) == before
