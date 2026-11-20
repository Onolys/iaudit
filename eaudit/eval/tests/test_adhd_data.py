"""Core self-tests (07 R10, 07a subset): committed fixtures stay valid and reproducible."""

import json

import pytest

from eaudit.contract import validate_request
from eval.adhd import DATA
from eval.build_adhd import build, main

FIXTURES = ["faithful", *[f"v{i}" for i in range(1, 9)]]


@pytest.mark.parametrize("fx", FIXTURES)
def test_committed_request_validates_against_schema(fx):
    req = json.loads((DATA / "requests" / f"{fx}.json").read_text(encoding="utf-8"))
    assert validate_request(req) == []


def test_rebuild_is_byte_identical_to_committed(tmp_path):
    main(tmp_path)
    built = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json*"))
    assert built == sorted(build())
    for rel in built:
        assert (tmp_path / rel).read_bytes() == (DATA / rel).read_bytes(), rel


def test_no_stray_generated_files():
    on_disk = {
        p.relative_to(DATA).as_posix()
        for sub in ("requests", "expected", "gold")
        for p in (DATA / sub).glob("*")
    }
    assert on_disk == set(build())


def test_expected_files_parse_and_name_their_fixture():
    for fx in FIXTURES:
        e = json.loads((DATA / "expected" / f"{fx}.json").read_text(encoding="utf-8"))
        assert e["fixture"] == f"adhd-{fx}"


def test_every_request_has_one_section_and_26_turns():
    for fx in FIXTURES:
        req = json.loads((DATA / "requests" / f"{fx}.json").read_text(encoding="utf-8"))
        assert len(req["assessment"]) == 1 and len(req["transcript"]) == 26
