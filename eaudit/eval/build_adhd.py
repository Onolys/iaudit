"""Deterministic spec -> committed fixture files.

Run from eaudit/:  uv run python -m eval.build_adhd
"""

import json
import sys
from pathlib import Path

from eval.adhd import DATA, dump_json, load_spec, make_request
from eval.gold import CONCERNS, GOLD_VERSION


def sentences_for(spec: dict, fixture: str) -> list[str]:
    """Faithful sentences with this fixture's single edit applied."""
    keys = sorted(spec["sentences"])
    out = [spec["sentences"][k] for k in keys]
    if fixture == "faithful":
        return out
    v = next(x for x in spec["variants"] if x["id"] == fixture)
    if v["op"] == "append":
        return [*out, v["text"]]
    out[keys.index(v["target"])] = v["text"]
    return out


def expected_for(spec: dict, fixture: str) -> dict:
    """Simple expected result (07 R5a): no evidence, slots or offsets."""
    if fixture == "faithful":
        return {
            "fixture": "adhd-faithful",
            "all_claims": {"verdict": "supported", "concerns_required": [], "concerns_allowed": []},
        }
    v = next(x for x in spec["variants"] if x["id"] == fixture)
    return {"fixture": f"adhd-{fixture}", "target_text": v["text"], **v["expected"]}


NOROLES = "v4-noroles"
NOROLES_EXPECTED = {
    "verdict": "insufficient_evidence",
    "concerns_required": ["unsupported_claim"],
    "concerns_allowed": [],
    "explanation_contains": [],
    "expect_warnings": ["ambiguous_speaker"],
}


def load_gold_spec() -> dict:
    return json.loads((DATA / "gold_spec.json").read_text(encoding="utf-8"))


def gold_rows(spec: dict, gspec: dict, fixture: str) -> list[dict]:
    """Gold claims for one fixture: faithful controls, with the variant's claim swapped in."""
    variant = (
        None if fixture == "faithful" else next(x for x in spec["variants"] if x["id"] == fixture)
    )
    keys = sorted(spec["sentences"])
    parts: list[tuple[str, dict]] = []  # (claim_text, gold spec entry), document order
    for k in keys:
        if variant and variant["op"] == "replace" and variant["target"] == k:
            parts.append(("target", gspec["targets"][fixture]))
        else:
            parts += [("control", c) for c in gspec["controls"][k]]
    if variant and variant["op"] == "append":
        parts.append(("target", gspec["targets"][fixture]))
    text = " ".join(sentences_for(spec, fixture))
    rows, cursor = [], 0
    for n, (role, entry) in enumerate(parts, 1):
        start = text.index(entry["claim_text"], cursor)
        end = start + len(entry["claim_text"])
        cursor = end
        target = role == "target"
        exp = (NOROLES_EXPECTED if fixture == NOROLES else variant["expected"]) if target else None
        first = exp["concerns_required"][0] if target and exp["concerns_required"] else None
        rows.append(
            {
                "gold_version": GOLD_VERSION,
                "fixture": f"adhd-{fixture}",
                "claim_id": f"g{n}",
                "section_index": 0,
                "claim_text": entry["claim_text"],
                "start": start,
                "end": end,
                "role_in_fixture": role,
                "bucket": CONCERNS.index(first) + 1 if first else None,
                "priority": ("P0" if int(fixture[1]) <= 5 else "P1") if target else "control",
                "verdict": exp["verdict"] if target else "supported",
                "concerns_required": exp["concerns_required"] if target else [],
                "concerns_allowed": exp["concerns_allowed"] if target else [],
                "explanation_contains": exp["explanation_contains"] if target else [],
                "evidence": entry["evidence"],
                "expect_warnings": exp.get("expect_warnings", []) if target else [],
                "slots": entry["slots"],
                "status": entry["status"],
            }
        )
    return rows


def build() -> dict[str, str]:
    """Relative path -> file content for every generated file."""
    spec = load_spec()
    gspec = load_gold_spec()
    files: dict[str, str] = {}
    for fx in ["faithful", *[v["id"] for v in spec["variants"]]]:
        req = make_request(spec, f"adhd-{fx}", sentences_for(spec, fx))
        files[f"requests/{fx}.json"] = dump_json(req)
        files[f"expected/{fx}.json"] = dump_json(expected_for(spec, fx))
        files[f"gold/{fx}.jsonl"] = _jsonl(gold_rows(spec, gspec, fx))
    # V4 with every role removed: the missing-role rule applies (not gated at POC)
    base = json.loads(files["requests/v4.json"])
    noroles = {
        **base,
        "request_id": f"adhd-{NOROLES}",
        "transcript": [{k: v for k, v in t.items() if k != "role"} for t in base["transcript"]],
    }
    files[f"requests/{NOROLES}.json"] = dump_json(noroles)
    files[f"expected/{NOROLES}.json"] = dump_json(
        {"fixture": f"adhd-{NOROLES}", "target_text": expected_for(spec, "v4")["target_text"],
         **NOROLES_EXPECTED}
    )  # fmt: skip
    gold_v4 = gold_rows(spec, gspec, "v4")
    for r in gold_v4:
        r["fixture"] = f"adhd-{NOROLES}"
    target = next(r for r in gold_v4 if r["role_in_fixture"] == "target")
    target.update(
        verdict=NOROLES_EXPECTED["verdict"],
        concerns_required=NOROLES_EXPECTED["concerns_required"],
        expect_warnings=NOROLES_EXPECTED["expect_warnings"],
        bucket=CONCERNS.index("unsupported_claim") + 1,
        status="proposed",
    )
    files[f"gold/{NOROLES}.jsonl"] = _jsonl(gold_v4)
    return files


def _jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)


def main(out_dir: Path = DATA) -> None:
    for rel, content in build().items():
        path = Path(out_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA)
