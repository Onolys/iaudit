"""Print per-bucket F1 deltas between two reports and flag the add-a-stage rule (>= +0.05)."""

import json
import sys
from pathlib import Path

THRESHOLD = 0.05


def deltas(a: dict, b: dict) -> list[dict]:
    rows = []
    for bucket in sorted(set(a["buckets"]) | set(b["buckets"]), key=int):
        ra, rb = a["buckets"].get(bucket), b["buckets"].get(bucket)
        fa = ra["f1"] if ra else None
        fb = rb["f1"] if rb else None
        delta = None if fa is None or fb is None else round(fb - fa, 4)
        rows.append(
            {
                "bucket": bucket,
                "concern": (rb or ra)["concern"],
                "f1_a": fa,
                "f1_b": fb,
                "delta": delta,
                "flag": delta is not None and delta >= THRESHOLD,
            }
        )
    return rows


def render(rows: list[dict]) -> str:
    def f(x):
        return "-" if x is None else f"{x:.2f}"

    lines = ["bucket  concern                           a      b      delta"]
    for r in rows:
        mark = "  <= +0.05: stage earns its cost" if r["flag"] else ""
        lines.append(
            f"{r['bucket']:>6}  {r['concern']:<32} {f(r['f1_a']):>5}  {f(r['f1_b']):>5}  "
            f"{'-' if r['delta'] is None else format(r['delta'], '+.2f'):>6}{mark}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m eval.compare a/report.json b/report.json")
        return 2
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args)
    print(render(deltas(a, b)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
