#!/usr/bin/env python3
"""Check mock audit fixtures against contract 1.2.0.

Each sample is a folder holding request.json and response.json. The script
checks the JSON schemas (when the jsonschema package is installed) and the
rules in docs/contracts/README.md that a schema cannot express.

Usage:
    python3 validate.py                 # every sample folder next to this file
    python3 validate.py 01-memory-basic # one or more named folders or paths
    python3 validate.py --show          # also print the text each span resolves to

Schema checks need jsonschema. Without it, only the rule checks run:
    uv run --with jsonschema python3 validate.py

Offsets are Unicode code points with an exclusive end. Python str already
counts that way, so plain slicing is correct here.
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parent.parent / "contracts"
VERSION = "1.2.0"
# A run of this many words copied from a turn into written text breaks rule 9.
COPY_WORDS = 6


def load_schemas():
    try:
        import jsonschema
    except ImportError:
        return None
    out = {}
    for name in ("request", "response"):
        schema = json.loads((CONTRACTS / f"audit-{name}.schema.json").read_text())
        out[name] = jsonschema.Draft202012Validator(schema)
    return out


def key(ptr):
    return (ptr["index"], ptr["char"])


def resolve(items, span):
    """Text a span selects, using the walk in the contract README."""
    s, e = span["start"], span["end"]
    if s["index"] == e["index"]:
        return items[s["index"]][s["char"]:e["char"]]
    parts = [items[s["index"]][s["char"]:]]
    parts += items[s["index"] + 1:e["index"]]
    parts.append(items[e["index"]][:e["char"]])
    return "\n".join(parts)


def check_span(items, span, where, errors, single_item):
    s, e = span["start"], span["end"]
    for name, ptr in (("start", s), ("end", e)):
        if not 0 <= ptr["index"] < len(items):
            errors.append(f"{where}: {name}.index {ptr['index']} is outside 0..{len(items) - 1}")
            return False
    if key(s) >= key(e):
        errors.append(f"{where}: start is not strictly before end")
        return False
    if s["char"] >= len(items[s["index"]]):
        errors.append(f"{where}: start.char {s['char']} is not inside item {s['index']} (length {len(items[s['index']])})")
        return False
    if e["char"] > len(items[e["index"]]):
        errors.append(f"{where}: end.char {e['char']} is past item {e['index']} (length {len(items[e['index']])})")
        return False
    if single_item and s["index"] != e["index"]:
        errors.append(f"{where}: a claim must stay inside one section")
        return False
    if s["index"] != e["index"] and e["char"] == 0:
        errors.append(f"{where}: cross-turn span ends at char 0")
        return False
    return True


def word_runs(text, n):
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def check_sample(folder, schemas, show):
    errors = []
    try:
        req = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        res = json.loads((folder / "response.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load: {exc}"]

    if schemas:
        for name, doc in (("request", req), ("response", res)):
            for err in schemas[name].iter_errors(doc):
                path = "/".join(str(p) for p in err.absolute_path) or "(root)"
                errors.append(f"{name} schema: {path}: {err.message}")
        if errors:
            return errors

    turns = [t["text"] for t in req["transcript"]]
    sections = [s["text"] for s in req["assessment"]]

    # Ids are log-only but must be unique.
    for label, items in (("turn", req["transcript"]), ("section", req["assessment"])):
        ids = [i["id"] for i in items]
        if len(ids) != len(set(ids)):
            errors.append(f"request: duplicate {label} id")

    # Rule 10: request_id echo.
    if req.get("request_id") != res.get("request_id"):
        errors.append(f"rule 10: request_id {res.get('request_id')!r} does not echo {req.get('request_id')!r}")

    # Rule 11 and warning references.
    claim_ids = [c["id"] for c in res["claims"]]
    skipped = set()
    for w in res["warnings"]:
        if w["code"] == "section_not_processed":
            idx = w.get("section_index")
            if idx is None or not 0 <= idx < len(sections):
                errors.append(f"warning: section_index {idx} is outside the assessment")
            skipped.add(idx)
        if "claim_id" in w and w["claim_id"] not in claim_ids:
            errors.append(f"warning: claim_id {w['claim_id']!r} is not a claim")
    if res["status"] == "partial" and not skipped:
        errors.append("rule 11: partial status without a section_not_processed warning")

    # Rule 7: claim ids unique.
    if len(claim_ids) != len(set(claim_ids)):
        errors.append("rule 7: duplicate claim id")

    copy_runs = set()
    for t in turns:
        copy_runs |= word_runs(t, COPY_WORDS)
    stamps = {t["timestamp"] for t in req["transcript"] if t.get("timestamp")}

    good_claims = []
    for c in res["claims"]:
        where = f"claim {c['id']}"
        if check_span(sections, c["span"], where, errors, single_item=True):
            good_claims.append(c)
            if c["span"]["start"]["index"] in skipped:
                errors.append(f"{where}: sits in a section reported as not processed")
        roles = [ev["role"] for ev in c["evidence"]]
        v = c["verdict"]
        # Rules 2-6.
        if v == "supported" and ("supporting" not in roles or "contradicting" in roles):
            errors.append(f"rule 2: {where} is supported without a supporting excerpt, or with a contradicting one")
        if v == "contradicted" and "contradicting" not in roles:
            errors.append(f"rule 3: {where} is contradicted without a contradicting excerpt")
        if v == "partially_supported" and not c["concerns"]:
            errors.append(f"rule 4: {where} is partially_supported without a concern")
        if v == "insufficient_evidence" and "contradicting" in roles:
            errors.append(f"rule 5: {where} is insufficient_evidence with a contradicting excerpt")
        if v == "out_of_scope" and (not c.get("out_of_scope_reason") or c["concerns"]):
            errors.append(f"rule 6: {where} is out_of_scope without a reason, or with concerns")
        if v != "out_of_scope" and "out_of_scope_reason" in c:
            errors.append(f"rule 6: {where} has out_of_scope_reason on verdict {v}")
        # Rule 7: evidence ids.
        ev_ids = [ev["id"] for ev in c["evidence"]]
        if len(ev_ids) != len(set(ev_ids)):
            errors.append(f"rule 7: {where} has duplicate evidence ids")
        for con in c["concerns"]:
            for ref in con["evidence_ids"]:
                if ref not in ev_ids:
                    errors.append(f"rule 7: {where} concern {con['type']} points at missing evidence {ref!r}")
        # Rule 1 for evidence.
        for ev in c["evidence"]:
            check_span(turns, ev["span"], f"{where} evidence {ev['id']}", errors, single_item=False)
        # Rule 9: written fields copy no transcript text and no timestamp.
        written = [c["explanation"], c.get("out_of_scope_reason") or "", c.get("suggested_revision") or ""]
        written += [con["explanation"] for con in c["concerns"]]
        written += [ev.get("note", "") for ev in c["evidence"]]
        for text in written:
            if word_runs(text, COPY_WORDS) & copy_runs:
                errors.append(f"rule 9: {where} copies {COPY_WORDS}+ words of transcript text")
            if any(st in text for st in stamps):
                errors.append(f"rule 9: {where} contains a transcript timestamp")

    # Rule 8: no overlap or nesting within a section.
    ordered = sorted(good_claims, key=lambda c: key(c["span"]["start"]))
    for a, b in zip(ordered, ordered[1:]):
        if key(b["span"]["start"]) < key(a["span"]["end"]):
            errors.append(f"rule 8: claims {a['id']} and {b['id']} overlap")

    if show and not errors:
        for c in ordered:
            print(f"  [{c['verdict']}] {c['id']}: {resolve(sections, c['span'])!r}")
            for ev in c["evidence"]:
                print(f"      {ev['role']} {ev['id']}: {resolve(turns, ev['span'])!r}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("samples", nargs="*", help="sample folders (default: all next to this script)")
    parser.add_argument("--show", action="store_true", help="print the text each span resolves to")
    args = parser.parse_args()

    if args.samples:
        folders = [Path(s) if Path(s).is_dir() else HERE / s for s in args.samples]
    else:
        folders = sorted(p for p in HERE.iterdir() if (p / "request.json").exists())
    if not folders:
        print("no sample folders found", file=sys.stderr)
        return 2

    schemas = load_schemas()
    if schemas is None:
        print("note: jsonschema not installed, skipping schema checks (uv run --with jsonschema python3 validate.py)")

    failed = 0
    for folder in folders:
        print(f"{folder.name}:")
        errors = check_sample(folder, schemas, args.show)
        if errors:
            failed += 1
            for err in errors:
                print(f"  FAIL {err}")
        else:
            print("  ok")
    print(f"{len(folders) - failed}/{len(folders)} samples passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
