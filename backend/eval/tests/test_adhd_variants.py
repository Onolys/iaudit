import json

import pytest

from eval.adhd import DATA, faithful_request, load_spec
from eval.build_adhd import build, main, sentences_for
from iaudit_backend.contract import validate_request


def test_builds_nine_requests_plus_the_optional_noroles_variant():
    out = build()
    assert sorted(k for k in out if k.startswith("requests/")) == sorted(
        f"requests/{n}.json" for n in ["faithful", *[f"v{i}" for i in range(1, 9)], "v4-noroles"]
    )


@pytest.mark.parametrize("n", range(1, 9))
def test_variant_valid_and_one_edit(n):
    spec = load_spec()
    req = json.loads(build()[f"requests/v{n}.json"])
    assert validate_request(req) == []
    assert req["request_id"] == f"adhd-v{n}"
    assert req["transcript"] == faithful_request()["transcript"]
    base = [spec["sentences"][k] for k in sorted(spec["sentences"])]
    var = sentences_for(spec, f"v{n}")
    v = next(x for x in spec["variants"] if x["id"] == f"v{n}")
    if v["op"] == "append":
        assert var == [*base, v["text"]]
    else:
        diffs = [i for i, (a, b) in enumerate(zip(base, var, strict=True)) if a != b]
        assert len(var) == len(base) and len(diffs) == 1
        assert base[diffs[0]] == spec["sentences"][v["target"]] and var[diffs[0]] == v["text"]
    assert req["assessment"][0]["text"] == " ".join(var)


def test_v1_uses_approved_wording():
    spec = load_spec()
    v1 = next(x for x in spec["variants"] if x["id"] == "v1")
    assert v1["text"] == "Alex loses attention in every meeting, several times a day."


def test_main_writes_files(tmp_path):
    main(tmp_path)
    assert (tmp_path / "requests" / "v3.json").is_file()
    assert (tmp_path / "requests" / "faithful.json").read_text() == (
        DATA / "requests" / "faithful.json"
    ).read_text()
