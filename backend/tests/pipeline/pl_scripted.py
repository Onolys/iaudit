"""A scripted LLM for the ADHD example: answers atomize / link / check from a per-claim table.

The check answers are the observations from 05's Variant map, so the full pipeline can be
replayed offline (no fixtures to regenerate).
"""

import json
import re

from atomize_helpers import FIXTURES, raw

from eval.adhd import faithful_request, load_spec, make_request
from iaudit_backend.atomize.models import AtomizerOutput
from iaudit_backend.check.models import VerifierOutput
from iaudit_backend.link.models import LinkerOutput
from iaudit_backend.llm import LLMResult

UNSPEC = [{"source": "unspecified", "speaker": None}]
TURNS = {i: t["text"] for i, t in enumerate(load_spec()["transcript"])}


def q(text, rate=None, bucket=None, basis="relative"):
    return {"raw": text, "rate_per_week": rate, "bucket_guess": bucket, "basis": basis}


# faithful claims a..k: (turns, role, observation fields)
FAITHFUL = {
    "a": ([3], "supporting", dict(frequency=[q("Most meetings"), q("3 to 4 a week", 3.5, basis="numeric")])),
    "b": ([7], "supporting", dict(certainty="hedged_light", frequency=[q("constantly"), q("every day", 7.0, basis="numeric")])),
    "c": ([9], "supporting", {}),
    "d": ([11], "supporting", {}),
    "e": ([11], "supporting", {}),
    "f": ([19], "supporting", dict(frequency=[q("twice a month", 0.46, basis="numeric")])),
    "g": ([23], "supporting", dict(frequency=[q("once a month", 0.23, basis="numeric")])),
    "h": ([15], "supporting", dict(timeframe="childhood", frequency=[q("constantly")])),
    "i": ([15], "supporting", dict(timeframe="childhood")),
    "j": ([25], "supporting", dict(timeframe="past")),
    "k": ([5], "supporting", dict(polarity="negated")),
}  # fmt: skip
SENTENCE_CLAIMS = {"S1": "a", "S2": "bc", "S3": "de", "S4": "fg", "S5": "hi", "S6": "j", "S7": "k"}


def _faithful_raws() -> dict[str, dict]:
    data = json.loads((FIXTURES / "adhd-faithful.atomize.s0.json").read_text())
    return {c["ref"]: c for c in data["claims"]}


def _variant_spec(vid: str):
    """(replaced sentence key | None, new claim raw, [(turns, role, obs)], flags)."""
    s = {
        "v1": (
            "S1",
            "Alex loses attention in every meeting, several times a day",
            dict(
                reported_by=UNSPEC,
                subject_speaker=None,
                quantities=[
                    {"kind": "frequency", "raw": "every meeting", "bucket": "always"},
                    {"kind": "frequency", "raw": "several times a day", "bucket": "always"},
                ],
            ),
            [
                (
                    [3],
                    "supporting",
                    dict(
                        frequency=[
                            q("Most meetings"),
                            q("three or four times a week", 3.5, basis="numeric"),
                        ]
                    ),
                )
            ],
            [],
        ),
        "v2": (
            "S7",
            "He makes frequent careless mistakes in reports",
            dict(reported_by=UNSPEC, subject_speaker=None),
            [([5], "contradicting", dict(relation="contradicts", polarity="negated"))],
            [],
        ),
        "v3": (
            None,
            "He frequently forgets appointments",
            dict(reported_by=UNSPEC, subject_speaker=None),
            [
                (
                    [21],
                    "contradicting",
                    dict(relation="contradicts", polarity="negated", experiencer="other_person"),
                )
            ],
            [],
        ),
        "v4": (
            None,
            "He is easily distracted by his surroundings",
            dict(reported_by=UNSPEC, subject_speaker=None),
            [([12, 13], "qualifying", {})],
            [],
        ),
        "v5": (
            None,
            "He currently forgets work assignments weekly",
            dict(reported_by=UNSPEC, subject_speaker=None, timeframe_explicit=True),
            [
                (
                    [17],
                    "qualifying",
                    dict(
                        timeframe="childhood",
                        conf="medium",
                        frequency=[q("once a week", 1.0, basis="numeric")],
                    ),
                )
            ],
            [],
        ),
        "v6": (
            "S4",
            "Both Alex and his partner agree he forgets errands about twice a month",
            dict(
                reported_by=[
                    {"source": "self", "speaker": "alex1"},
                    {"source": "informant", "speaker": "sam1"},
                ],
                subject_speaker=None,
                quantities=[
                    {
                        "kind": "frequency",
                        "raw": "twice a month",
                        "bucket": "sometimes",
                        "rate_per_week": 0.46,
                    }
                ],
            ),
            [
                ([19], "supporting", dict(frequency=[q("twice a month", 0.46, basis="numeric")])),
                ([23], "qualifying", dict(frequency=[q("once a month", 0.23, basis="numeric")])),
            ],
            [{"type": "conflicting_accounts_flattened", "keys": [0, 1], "conf": "high"}],
        ),
        "v7": (
            "S3",
            "The unfinished bathroom shows his difficulty completing tasks",
            dict(reported_by=UNSPEC, subject_speaker=None),
            [([11], "supporting", {})],
            [{"type": "context_stripping", "keys": [0], "conf": "high"}],
        ),
        "v8": (
            "S6",
            "His distractibility caused a negative performance review",
            dict(reported_by=UNSPEC, subject_speaker=None, timeframe="past"),
            [([25], "qualifying", {})],
            [{"type": "unsupported_causal_link", "keys": [0], "conf": "high"}],
        ),
    }
    return s[vid]


class Scripted:
    """Answers by call_tag and claim proposition. `delays` adds per-tag sleeps (seconds)."""

    def __init__(self, vid: str | None = None):
        self.vid = vid
        raws = _faithful_raws()
        self.table: dict[str, dict] = {}  # proposition -> {raw, link, flags}
        replaced = None
        extra = None
        if vid and vid != "faithful":
            replaced, text, over, links, flags = _variant_spec(vid)
            extra = (text, over, links, flags)
        drop = set(SENTENCE_CLAIMS[replaced]) if replaced else set()
        self.claims: list[dict] = []
        for ref, (turns, role, obs) in FAITHFUL.items():
            if ref in drop:
                continue
            r = {**raws[ref]}
            self.table[r["proposition"]] = dict(raw=r, link=[(turns, role, obs)], flags=[])
            self.claims.append(r)
        if extra:
            text, over, links, flags = extra
            r = raw(ref="z", segments=[text], proposition=text + ".", **over)
            self.table[r["proposition"]] = dict(raw=r, link=links, flags=flags)
            self.claims.append(r)
        self.request = make_request(
            load_spec(), f"adhd-{vid or 'faithful'}", self.sentences(replaced, extra)
        )
        self.calls: list[str] = []

    def sentences(self, replaced, extra) -> list[str]:
        spec = load_spec()
        keys = sorted(spec["sentences"])
        out = [spec["sentences"][k] for k in keys]
        if extra is None:
            return out
        text = extra[0] + "."
        if replaced:
            out[keys.index(replaced)] = text
        else:
            out.append(text)
        return out

    # -- the client -----------------------------------------------------------------------
    async def complete_json(self, req, metrics=None):
        self.calls.append(req.call_tag)
        fn = getattr(self, f"_{req.call_tag}")
        return LLMResult(parsed=fn(req))

    def _atomize(self, req):
        return AtomizerOutput.model_validate({"claims": self.claims, "links": []})

    def _proposition(self, req) -> str:
        m = re.search(r"^Claim: (.*)$", req.user, re.M)
        return m.group(1)

    def _link(self, req):
        entry = self.table[self._proposition(req)]
        items = []
        for n, (turns, role, _) in enumerate(entry["link"], 1):
            items.append(
                {
                    "key": f"e{n}",
                    "role": role,
                    "link_type": "quote",
                    "segments": [{"turn": t, "text": TURNS[t]} for t in turns],
                }  # fmt: skip
            )
        return LinkerOutput.model_validate({"items": items})

    def _check(self, req):
        entry = self.table[self._proposition(req)]
        keys = re.findall(r"^- key=(\S+)", req.user, re.M)
        items = []
        for key, (_, _, obs) in zip(keys, entry["link"], strict=True):
            fields = dict(obs)
            rel = fields.pop("relation", "entails")
            items.append(
                {"key": key, "relation": rel, "conf": fields.pop("conf", "high"), **fields}
            )
        flags = [{**f, "keys": [keys[i] for i in f["keys"]]} for f in entry["flags"]]
        return VerifierOutput.model_validate({"items": items, "flags": flags})


def faithful_request_dict() -> dict:
    return faithful_request()
