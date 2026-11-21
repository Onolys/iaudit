"""Deterministic, sleep-free, schema-valid fake adapters (`ADAPTERS=stub`) and magic-title
failure injection (PRD R6, AC15).

Magic session titles (the worker passes the session title to the fakes as
`params.options["stub_title"]` for `Stt` and `params["stub_title"]` for `Evaluation`; real
adapters ignore it). Matching is by substring.
"""

import hashlib
from typing import Any

from onolys_core.engine import PackRef, RunContext
from onolys_core.stt import AudioRef, SttParams, SttRun, Word
from onolys_core.stt.base import BaseSttAdapter
from onolys_core.transcript import Transcript

from onolys_api.adapters.base import AdapterError, EvaluationOutput, ProgressCb

# failure injection
FAIL_PAUDIT = "[fail:paudit]"  # run and session `failed`
FAIL_EAUDIT = "[fail:eaudit]"  # report_ready, reasons_audit failed + warning
FAIL_TIPS = "[fail:tips]"  # report_ready, tips=[] + warning tips_failed
FAIL_NO_SPEECH = "[fail:no_speech]"  # transcript with 0 turns
FAIL_SPEAKERS = "[fail:speakers_not_separated]"  # one speaker only
FAIL_TRANSCRIPTION = "[fail:transcription_failed]"  # provider error on poll
STUB_TITLE_KEY = "stub_title"

FAKE_CREATED_AT = "2026-01-01T00:00:00Z"
ADAPTER_VERSION = "fake-1"

# Clearly synthetic two-person script (A = clinician, B = client); 70+ words.
_SCRIPT: tuple[tuple[str, str], ...] = (
    ("A", "Thanks for coming in today, what would you like to talk about?"),
    ("B", "I have been thinking about cutting back, but it feels hard."),
    ("A", "So part of you wants a change and part of you is unsure."),
    ("B", "Yes, exactly, I worry I will not manage without it."),
    ("A", "You care about doing this well, and that worry shows it."),
    ("B", "I suppose so, I want to be healthier for my family."),
    ("A", "What would a first small step look like for you this week?"),
    ("B", "Maybe skipping it on weekday evenings, just to see how it goes."),
)
_WORD_MS = 400
_GAP_MS = 2500  # above the 2 s turn gap, so same-speaker lines stay separate turns


def _mode(title: str | None) -> str:
    t = title or ""
    for marker, mode in (
        (FAIL_NO_SPEECH, "no_speech"),
        (FAIL_SPEAKERS, "one_speaker"),
        (FAIL_TRANSCRIPTION, "transcription_failed"),
    ):
        if marker in t:
            return mode
    return "ok"


def _script_words(mode: str) -> list[Word]:
    if mode == "no_speech":
        return []
    words: list[Word] = []
    t = 0
    for speaker, line in _SCRIPT:
        for token in line.split():
            words.append(
                Word(
                    text=token,
                    start_ms=t,
                    end_ms=t + _WORD_MS,
                    speaker="A" if mode == "one_speaker" else speaker,
                )
            )
            t += _WORD_MS
        t += _GAP_MS
    return words


class FakeStt(BaseSttAdapter):
    """Fake `Stt`: replays the synthetic script. Records every `start` call."""

    def __init__(self, *, polls_before_ready: int = 0) -> None:
        self._polls_before_ready = polls_before_ready
        self._jobs: dict[str, tuple[str, str, int]] = {}  # handle -> (mode, language, polls)
        self.start_calls = 0
        self.started: list[tuple[AudioRef, SttParams]] = []
        self.poll_calls = 0

    async def _submit(self, audio: AudioRef, params: SttParams) -> str:
        self.start_calls += 1
        self.started.append((audio, params))
        mode = _mode(params.options.get(STUB_TITLE_KEY))
        digest = hashlib.sha256(audio.uri.encode()).hexdigest()[:12]
        handle = f"fake-stt:{digest}:{self.start_calls}"
        self._jobs[handle] = (mode, params.language, 0)
        return handle

    async def _fetch(self, handle: str) -> tuple[list[Word], SttRun] | None:
        self.poll_calls += 1
        if handle not in self._jobs:
            raise AdapterError("transcription_failed")  # unknown/expired handle
        mode, lang, polls = self._jobs[handle]
        if polls < self._polls_before_ready:
            self._jobs[handle] = (mode, lang, polls + 1)
            return None
        if mode == "transcription_failed":
            raise AdapterError("transcription_failed")
        run = SttRun(
            provider="fake",
            model="fake",
            language_requested=lang,
            language_detected="en" if lang == "auto" else lang,
            adapter_version=ADAPTER_VERSION,
        )
        return _script_words(mode), run


# ---- Evaluation ----

_GLOBALS = (
    ("cct", "Cultivating Change Talk"),
    ("sst", "Softening Sustain Talk"),
    ("partnership", "Partnership"),
    ("empathy", "Empathy"),
)
_BEHAVIOURS = (("reflection_simple", "Simple Reflection"), ("question", "Question"))
_PROTOCOL = {"id": "fake-pack", "version": "0.0.0", "pack_hash": "0" * 16, "label": "Fake pack"}
# Mirrors paudit.pack.PACK_FORMAT (string); api does not depend on the paudit package.
_PACK_FORMAT = "0.0.1"


def _run_info(engine: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": engine,
        "code_version": str(params.get("code_version") or "fake"),
        "preset": params.get("preset"),
        "routes": {},
        "stt": None,
        "pack": {"id": "fake-pack", "version": "0.0.0", "hash": "0" * 16},
        "prompt_hashes": {},
        "n_runs": int(params.get("n_runs") or 1),
        "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    }


def _subject_quotes(transcript: Transcript, subject: str) -> list[tuple[str, str]]:
    """Up to 3 (turn_id, quote) from the subject's turns; quote is a real substring."""
    out = []
    for turn in transcript.turns:
        if turn.speaker == subject and turn.text.strip():
            out.append((turn.id, turn.text))
        if len(out) == 3:
            break
    return out


def _paudit_result(
    transcript: Transcript, subject: str, params: dict[str, Any], quotes: list[tuple[str, str]]
) -> dict[str, Any]:
    n_runs = int(params.get("n_runs") or 1)
    instances = [
        {
            "id": f"i{i + 1}",
            "volley_id": f"v{i + 1}",
            "turn_id": tid,
            "start": 0,
            "end": len(q),
            "quote": q,
            "code": _BEHAVIOURS[i % 2][0],
            "counted": True,
            "rationale": "Synthetic fixture rationale.",
        }
        for i, (tid, q) in enumerate(quotes)
    ]
    counts = {bid: sum(1 for x in instances if x["code"] == bid) for bid, _ in _BEHAVIOURS}
    globals_ = {
        gid: {"score": 3, "source": "model", "raw_score": 3, "reason": "Synthetic.", "evidence": []}
        for gid, _ in _GLOBALS
    }
    run = {
        "run_index": 0,
        "instances": instances,
        "counts": counts,
        "globals": globals_,
        "summaries": {},
        "warnings": [],
    }
    stat = lambda v: {"mean": float(v), "min": v, "max": v, "values": [v] * n_runs}  # noqa: E731
    return {
        "schema_version": "0.0.1",
        "protocol": {
            **{k: _PROTOCOL[k] for k in ("id", "version", "pack_hash")},
            "pack_format": _PACK_FORMAT,
        },
        "language": str(params.get("language") or "en"),
        "change_goal": str(params.get("change_goal") or ""),
        "coded_span": params.get("coded_span"),
        "subject_speaker": subject,
        "n_runs": n_runs,
        "results": [{**run, "run_index": i} for i in range(n_runs)],
        "aggregate": {
            "counts": {k: stat(v) for k, v in counts.items()},
            "globals": {gid: stat(3) for gid, _ in _GLOBALS},
            "summaries": {},
            "representative_run": 0,
        },
        "warnings": [],
        "run_info": _run_info("paudit", params),
    }


def _global_diff(clinician: float | None, onolys: float) -> dict[str, Any]:
    """Minimal score_diff `Diff` (mirrors onolys_evaluation.compare.compare_item; >=1 differs)."""
    if clinician is None:
        return {"signed": None, "abs": None, "direction": None, "status": "not_rated"}
    signed = onolys - clinician
    a = abs(signed)
    return {
        "signed": signed,
        "abs": a,
        "direction": "same" if signed == 0 else "onolys_higher" if signed > 0 else "onolys_lower",
        "status": "differs" if a >= 1 else "agree",
        "within_one": a <= 1,
    }


class FakeEvaluation:
    """Fake `Evaluation`: schema-valid report built from the transcript; calls `progress_cb`
    for every stage in a fixed order; magic-title failure injection."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(
        self,
        ctx: RunContext,
        pack: PackRef | None,
        transcript: Transcript,
        speaker_map: dict[str, str],
        params: dict[str, Any],
        rating: dict[str, Any] | None,
        progress_cb: ProgressCb | None = None,
    ) -> EvaluationOutput:
        self.calls += 1
        title = str(params.get(STUB_TITLE_KEY) or "")

        def cb(stage: str, status: str) -> None:
            if progress_cb is not None:
                progress_cb(stage, status)  # type: ignore[arg-type]

        cb("paudit", "started")
        cb("eaudit", "started")
        if FAIL_PAUDIT in title:
            cb("paudit", "failed")
            raise AdapterError("paudit_failed")
        cb("paudit", "done")

        subject = speaker_map["subject"]
        quotes = _subject_quotes(transcript, subject)
        paudit = _paudit_result(transcript, subject, params, quotes)
        warnings: list[dict[str, Any]] = []

        has_rating = rating is not None
        if not has_rating:
            reasons: dict[str, Any] = {"status": "skipped", "items": []}
            eaudit = None
            cb("eaudit", "done")
        elif FAIL_EAUDIT in title:
            reasons = {"status": "failed", "items": []}
            eaudit = None
            warnings.append({"code": "reasons_audit_failed"})
            cb("eaudit", "failed")
        else:
            reasons = {"status": "ran", "items": []}
            eaudit = {"status": "ran", "claims": []}
            cb("eaudit", "done")

        cb("tips", "started")
        if FAIL_TIPS in title:
            tips: list[dict[str, Any]] = []
            warnings.append({"code": "tips_failed"})
            cb("tips", "failed")
        else:
            tips = [
                {
                    "rank": i + 1,
                    "item_id": _BEHAVIOURS[i % 2][0],
                    "observation": "Synthetic observation.",
                    "quote": {"turn_id": tid, "start": 0, "end": len(q), "text": q},
                    "alternative": "Synthetic alternative.",
                    "why_it_matters": "Synthetic reason.",
                }
                for i, (tid, q) in enumerate(quotes)
            ]
            cb("tips", "done")
        cb("compare", "started")
        scorecard = [
            {
                "item_id": gid,
                "kind": "global",
                "label": label,
                "clinician": {"value": 3 if has_rating else None},
                "onolys": {"value": 3, "mean": 3.0, "min": 3, "max": 3, "values": [3]},
                "diff": _global_diff(3 if has_rating else None, 3),
            }
            for gid, label in _GLOBALS
        ]
        cb("compare", "done")
        cb("assemble", "started")
        n_runs = int(params.get("n_runs") or 1)
        stt = transcript.stt_run.model_dump() if transcript.stt_run else None
        report = {
            "schema_version": "0.0.1",
            "created_at": FAKE_CREATED_AT,
            "header": {
                "change_goal": str(params.get("change_goal") or ""),
                "protocol": _PROTOCOL,
                "language": str(params.get("language") or "en"),
                "coded_span": params.get("coded_span"),
                "subject_speaker": subject,
                "n_runs": n_runs,
                "models": {},
                "stt": stt,
                "preset": params.get("preset"),
                "code_version": str(params.get("code_version") or "fake"),
                "params": {},
                "has_clinician_rating": has_rating,
                "rating_coverage": {
                    "rated": len(_GLOBALS) if has_rating else 0,
                    "total": len(_GLOBALS),
                },
            },
            "layout": [{"section": "scorecard", "title": "Scorecard"}],
            "scorecard": scorecard,
            "globals": [],
            "behaviours": [],
            "summaries": [],
            "reasons_audit": reasons,
            "tips": tips,
            "method": {
                "statement": "Synthetic fixture report.",
                "limits": [],
                "not_official_miti_coding": True,
                "citation": "n/a",
            },
            "aggregates": {
                "globals_compared": len(_GLOBALS) if has_rating else 0,
                "avg_abs_global_difference": 0.0 if has_rating else None,
                "within_one_share": 1.0 if has_rating else None,
                "counts_flagged": None,
            },
            "warnings": warnings,
            "run_info": {
                "evaluation": _run_info("evaluation", params),
                "paudit": paudit["run_info"],
                "eaudit": _run_info("eaudit", params) if eaudit else None,
            },
        }
        if ctx.request_id:
            report["request_id"] = ctx.request_id
        cb("assemble", "done")
        artifacts = {"paudit": paudit, "eaudit": eaudit, "tips": {"valid": tips, "proposals": []}}
        return EvaluationOutput(report=report, artifacts=artifacts)
