"""Generate `docs/contracts/public/*.schema.json` from the API's request/response models:
`python -m onolys_api.contracts [--check]`. The error schema is hand-written (it is the shared
contract with eaudit's) and checked against the model by a test."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

from onolys_api.routes.audio import AudioUploadRequest, AudioUploadResponse
from onolys_api.routes.rating import RatingRequest, RatingSaved, RatingView
from onolys_api.routes.runs import ReportList, ReportView, RunList, RunRequest, RunStarted, RunView
from onolys_api.routes.sessions import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionDetail,
    SessionList,
)
from onolys_api.routes.speakers import ConfirmRequest, ConfirmResponse, SpeakersView, TranscriptView

OUT_DIR = Path(__file__).resolve().parents[3] / "docs/contracts/public"
MODELS: dict[str, type[BaseModel]] = {
    "create-session-request": CreateSessionRequest,
    "create-session-response": CreateSessionResponse,
    "session-detail": SessionDetail,
    "session-list": SessionList,
    "audio-upload-request": AudioUploadRequest,
    "audio-upload-response": AudioUploadResponse,
    "rating-request": RatingRequest,
    "rating-saved": RatingSaved,
    "rating-view": RatingView,
    "speakers-view": SpeakersView,
    "confirm-request": ConfirmRequest,
    "confirm-response": ConfirmResponse,
    "transcript-view": TranscriptView,
    "run-request": RunRequest,
    "run-started": RunStarted,
    "run-view": RunView,
    "run-list": RunList,
    "report-view": ReportView,
    "report-list": ReportList,
}


def render_all() -> dict[str, str]:
    out: dict[str, str] = {}
    for stem, model in MODELS.items():
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{stem}.schema.json",
            **model.model_json_schema(mode="serialization"),
        }
        out[f"{stem}.schema.json"] = (
            json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="onolys_api.contracts")
    p.add_argument("--check", action="store_true", help="fail if the committed files are stale")
    args = p.parse_args(argv)
    stale = []
    for name, text in render_all().items():
        path = OUT_DIR / name
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
    if stale:
        sys.stderr.write(f"stale contract files: {', '.join(stale)}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
