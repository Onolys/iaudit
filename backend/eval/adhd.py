"""ADHD fixture helpers: load the spec and build contract requests from it."""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "adhd"


def load_spec() -> dict:
    return json.loads((DATA / "spec.json").read_text(encoding="utf-8"))


def canonical_transcript(transcript: list[dict]) -> str:
    """Stable serialisation used for the sha256 pin (speaker, role, text only)."""
    rows = [{"speaker": t["speaker"], "role": t["role"], "text": t["text"]} for t in transcript]
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_request(spec: dict, request_id: str, sentences: list[str]) -> dict:
    return {
        "schema_version": "1.1.0",
        "request_id": request_id,
        "transcript": [dict(t) for t in spec["transcript"]],
        "assessment": [{**spec["section"], "text": " ".join(sentences)}],
    }


def faithful_request() -> dict:
    spec = load_spec()
    return make_request(
        spec, "adhd-faithful", [spec["sentences"][k] for k in sorted(spec["sentences"])]
    )


def dump_json(obj) -> str:
    """Single serialisation for every committed fixture file (byte-stable)."""
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"
