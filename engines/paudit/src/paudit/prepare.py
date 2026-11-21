"""Pure steps before any model call (PRD R2 steps 1-3): role marking, span selection,
input checks and volley building. Protocol-agnostic: "subject" / "other" roles only."""

from dataclasses import dataclass, field
from typing import Any

from onolys_core import InputError
from onolys_core.transcript import Transcript, Turn

from paudit.hooks import Hooks
from paudit.pack import Pack
from paudit.result import ResultWarning

SUBJECT = "subject"
OTHER = "other"


@dataclass(frozen=True)
class RoleTurn:
    turn: Turn
    role: str  # "subject" | "other"


@dataclass(frozen=True)
class Volley:
    id: str  # v1..vN
    turns: list[Turn]  # consecutive subject turns
    prev_other: Turn | None  # most recent other-speaker turn before the volley (context only)


@dataclass(frozen=True)
class CheckInput:
    """What the `check_input` hook sees."""

    turns: list[RoleTurn]  # selected turns
    params: dict[str, Any]
    duration_ms: int | None


@dataclass
class Prepared:
    turns: list[RoleTurn]
    volleys: list[Volley]
    warnings: list[ResultWarning] = field(default_factory=list)
    duration_ms: int | None = None


def _words(text: str) -> int:
    return len(text.split())


def mark_roles(
    transcript: Transcript, speaker_map: dict[str, Any]
) -> tuple[list[RoleTurn], list[ResultWarning]]:
    """`speaker_map["subject"]` is the subject's speaker id. Every other speaker is `other`.
    If the map also names `other`, a speaker matching neither (or no speaker at all) is
    unknown: treated as other, with one `unknown_speaker` warning."""
    subject = speaker_map.get(SUBJECT)
    if not subject:
        raise InputError("speaker_map.subject is required")
    other = speaker_map.get(OTHER)
    out: list[RoleTurn] = []
    unknown: list[str] = []
    for t in transcript.turns:
        if t.speaker == subject:
            out.append(RoleTurn(t, SUBJECT))
            continue
        if t.speaker is None or t.speaker == "" or (other is not None and t.speaker != other):
            unknown.append(t.id)
        out.append(RoleTurn(t, OTHER))
    warnings = []
    if unknown:
        shown = ", ".join(unknown[:5]) + (" ..." if len(unknown) > 5 else "")
        warnings.append(
            ResultWarning(
                code="unknown_speaker",
                detail=f"{len(unknown)} turn(s) with unknown speaker treated as other: {shown}",
            )
        )
    return out, warnings


def select_turns(
    turns: list[RoleTurn], coded_span: dict[str, Any] | None
) -> tuple[list[RoleTurn], list[ResultWarning]]:
    """Keep turns overlapping the span: `start_ms < to_s*1000 and end_ms > from_s*1000`
    (a missing `end_ms` falls back to `start_ms`). Partly-inside turns are kept whole. No turn
    has a timestamp -> span ignored + `span_ignored`. A turn without `start_ms` is kept."""
    span = coded_span or {}
    from_s, to_s = span.get("from_s"), span.get("to_s")
    if from_s is None and to_s is None:
        return list(turns), []
    if not any(rt.turn.start_ms is not None for rt in turns):
        return list(turns), [
            ResultWarning(code="span_ignored", detail="transcript has no timestamps")
        ]
    lo = from_s * 1000 if from_s is not None else None
    hi = to_s * 1000 if to_s is not None else None
    kept = []
    for rt in turns:
        start = rt.turn.start_ms
        if start is None:
            kept.append(rt)
            continue
        end = rt.turn.end_ms if rt.turn.end_ms is not None else start
        if (hi is None or start < hi) and (lo is None or end > lo):
            kept.append(rt)
    return kept, []


def build_volleys(turns: list[RoleTurn], volley_cfg: dict[str, Any]) -> list[Volley]:
    """Consecutive subject turns = one volley. An other-speaker turn breaks it when it has at
    least `min_other_words` words (default 0: any other turn breaks)."""
    min_words = int(volley_cfg.get("min_other_words", 0))
    volleys: list[Volley] = []
    current: list[Turn] = []
    prev_other: Turn | None = None
    current_prev: Turn | None = None

    def flush() -> None:
        nonlocal current
        if current:
            volleys.append(Volley(f"v{len(volleys) + 1}", current, current_prev))
            current = []

    for rt in turns:
        if rt.role == SUBJECT:
            if not current:
                current_prev = prev_other
            current.append(rt.turn)
        else:
            prev_other = rt.turn
            if _words(rt.turn.text) >= min_words:
                flush()
    flush()
    return volleys


def _duration_ms(
    transcript: Transcript, turns: list[RoleTurn], coded_span: dict[str, Any] | None, applied: bool
) -> int | None:
    starts = [rt.turn.start_ms for rt in turns if rt.turn.start_ms is not None]
    ends = [
        rt.turn.end_ms if rt.turn.end_ms is not None else rt.turn.start_ms
        for rt in turns
        if rt.turn.start_ms is not None
    ]
    if not starts:
        return transcript.duration_ms
    lo = min(starts)
    hi = max(ends)
    if transcript.duration_ms is not None and not applied:
        return transcript.duration_ms
    span = coded_span or {}
    if applied:
        if span.get("from_s") is not None:
            lo = span["from_s"] * 1000
        if span.get("to_s") is not None:
            hi = span["to_s"] * 1000
    return max(hi - lo, 0)


def run_input_checks(
    pack: Pack, turns: list[RoleTurn], params: dict[str, Any], duration_ms: int | None
) -> list[ResultWarning]:
    """Pack `input_checks`: severity `error` raises `InputError`, `warn` returns a warning."""
    warnings: list[ResultWarning] = []
    n_subject = sum(rt.role == SUBJECT for rt in turns)
    n_other = len(turns) - n_subject
    for chk in pack.data.get("input_checks", []):
        kind, value = chk["kind"], chk["value"]
        code = "short_session"
        if kind == "duration_max":
            bad = duration_ms is not None and duration_ms > value * 60_000
            msg = f"session longer than {value} min"
            code = "session_too_long"
        elif kind == "duration_min":
            bad = duration_ms is not None and duration_ms < value * 60_000
            msg = f"session shorter than {value} min"
        elif kind == "param_required":
            bad = params.get(value) in (None, "")
            msg = f"parameter '{value}' is required"
            code = "missing_param"
        elif kind == "min_subject_turns":
            bad = n_subject < value
            msg = f"fewer than {value} subject turns ({n_subject})"
        else:  # min_other_turns
            bad = n_other < value
            msg = f"fewer than {value} other-speaker turns ({n_other})"
        if not bad:
            continue
        if chk["severity"] == "error":
            raise InputError(f"{chk['id']}: {msg}")
        warnings.append(ResultWarning(code=code, detail=f"{chk['id']}: {msg}"))
    return warnings


def _coerce(w: Any) -> ResultWarning:
    return w if isinstance(w, ResultWarning) else ResultWarning(**w)


def prepare(
    transcript: Transcript,
    pack: Pack,
    params: dict[str, Any],
    hooks: Hooks | None = None,
) -> Prepared:
    """Roles -> select by span -> input checks (+ `check_input` hook) -> volleys.
    Checks run on the selected turns, so a short span counts as a short session."""
    speaker_map = params.get("speaker_map") or {}
    role_turns, warnings = mark_roles(transcript, speaker_map)
    coded_span = params.get("coded_span")
    selected, span_warn = select_turns(role_turns, coded_span)
    warnings += span_warn
    applied = (
        bool(coded_span)
        and not span_warn
        and (coded_span.get("from_s") is not None or coded_span.get("to_s") is not None)
    )
    duration = _duration_ms(transcript, selected, coded_span, applied)
    warnings += run_input_checks(pack, selected, params, duration)
    if hooks is not None and hooks.check_input is not None:
        extra = hooks.check_input(CheckInput(selected, params, duration), pack.data) or []
        warnings += [_coerce(w) for w in extra]
    volleys = build_volleys(selected, pack.data["volley"])
    return Prepared(selected, volleys, warnings, duration)
