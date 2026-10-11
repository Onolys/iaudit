"""Deterministic spec -> committed fixture files.

Run from backend/:  uv run python -m eval.build_adhd
"""

import sys
from pathlib import Path

from eval.adhd import DATA, dump_json, load_spec, make_request


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


def build() -> dict[str, str]:
    """Relative path -> file content for every generated file."""
    spec = load_spec()
    files: dict[str, str] = {}
    for fx in ["faithful", *[v["id"] for v in spec["variants"]]]:
        req = make_request(spec, f"adhd-{fx}", sentences_for(spec, fx))
        files[f"requests/{fx}.json"] = dump_json(req)
    return files


def main(out_dir: Path = DATA) -> None:
    for rel, content in build().items():
        path = Path(out_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA)
