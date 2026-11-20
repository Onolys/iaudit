"""Command line for the protocol-audit engine.

    python -m paudit.cli run --pack <id@version> --transcript f.json --params p.json
        [--stub expected.yaml [--stub-fixture NAME]] [--replay DIR] [--record DIR]
        [--preset NAME] [--out result.json]

`run` rates one transcript and prints the result JSON (or writes `--out`). Client choice:
`--stub` answers from a fixtures `expected.yaml` (offline, fixture name defaults to the transcript
file name without extension); `--replay DIR` replays recorded requests through core's
`FixtureClient` (offline); with neither, the live client for `--preset` is used.
`--record DIR` wraps a stub or live client and writes recordings into DIR for later replay.

    python -m paudit.cli check --pack <id@version> --preset NAME [--thresholds FILE] [--stub]

`check` runs the pack's fixtures (`<pack>/fixtures/expected.yaml`) on the live client, prints
count MAE, globals within 1, bad-output/retry rate, p95 latency and tokens, and exits 1 when a
value is past `thresholds.yaml` (see paudit.check). `--stub` answers from expected.yaml (offline).
Never prints a key.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from onolys_core import OnolysError
from onolys_core.llm import FixtureClient, LLMConfig, RecordingClient, make_client
from onolys_core.transcript import Transcript

from paudit import check as check_mod
from paudit.engine import run
from paudit.pack import load_pack
from paudit.stub import ExpectedStubClient


def _build_client(args: argparse.Namespace, transcript_path: Path):
    if args.replay:
        return FixtureClient(args.replay)
    if args.stub:
        name = args.stub_fixture or transcript_path.stem
        client = ExpectedStubClient(args.stub, name)
    else:
        client = make_client(LLMConfig(llm_mode="live", preset=args.preset))
    if args.record:
        client = RecordingClient(client, args.record)
    return client


def _cmd_run(args: argparse.Namespace) -> int:
    tpath = Path(args.transcript)
    transcript = Transcript.model_validate_json(tpath.read_text(encoding="utf-8"))
    params = json.loads(Path(args.params).read_text(encoding="utf-8"))
    if args.preset:
        params.setdefault("preset", args.preset)
    pack = load_pack(args.pack)
    client = _build_client(args, tpath)
    result = asyncio.run(run(transcript, pack, params, client))
    text = result.model_dump_json(indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    pack = load_pack(args.pack)
    fixtures = pack.root / "fixtures"
    th = check_mod.load_thresholds(Path(args.thresholds or fixtures / "thresholds.yaml"))
    if args.stub:

        def client_for(name: str):
            return ExpectedStubClient(fixtures / "expected.yaml", name)

    else:
        live = make_client(LLMConfig(llm_mode="live", preset=args.preset))

        def client_for(name: str):
            return live

    rep = asyncio.run(check_mod.run_check(pack, fixtures, client_for, th))
    print(check_mod.format_report(rep))
    return 0 if rep.passed else 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paudit.cli", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="rate one transcript against a pack")
    r.add_argument("--pack", required=True, help="pack reference id@version or a pack directory")
    r.add_argument("--transcript", required=True, help="transcript JSON file")
    r.add_argument("--params", required=True, help="params JSON file (speaker_map, change_goal)")
    r.add_argument("--stub", metavar="EXPECTED_YAML", help="offline: answer from expected.yaml")
    r.add_argument("--stub-fixture", metavar="NAME", help="fixture name inside --stub file")
    r.add_argument("--replay", metavar="DIR", help="offline: replay recordings in DIR")
    r.add_argument("--record", metavar="DIR", help="write recordings of every call into DIR")
    r.add_argument("--preset", help="route preset (live runs; provenance otherwise)")
    r.add_argument("--out", help="write the result JSON here instead of stdout")
    r.set_defaults(func=_cmd_run)
    c = sub.add_parser("check", help="run pack fixtures on the live model; gate on thresholds")
    c.add_argument("--pack", required=True, help="pack id@version or a pack directory")
    c.add_argument("--preset", help="route preset (default: the default preset)")
    c.add_argument("--thresholds", metavar="FILE", help="default: <pack>/fixtures/thresholds.yaml")
    c.add_argument("--stub", action="store_true", help="offline: answer from expected.yaml")
    c.set_defaults(func=_cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except (OnolysError, OSError, ValueError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
