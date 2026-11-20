"""Generate the committed OpenAPI contract: `python -m onolys_api.openapi [--out PATH|-]`."""

import argparse
import json
import sys
from pathlib import Path

from onolys_api.app import create_app
from onolys_api.config import Settings

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "openapi.json"


def render() -> str:
    # fixed settings: output must not depend on the caller's environment
    app = create_app(Settings(env="test", service_mode="combined", auth_mode="fake"))
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="onolys_api.openapi")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="output path, or - for stdout")
    args = p.parse_args(argv)
    text = render()
    if args.out == "-":
        sys.stdout.write(text)
    else:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
