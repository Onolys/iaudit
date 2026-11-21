"""R2: rating-card validation, code only (no parser, no model). Issues carry a path and a code,
never card text. Drafts (`final=False`) check shape and limits; final adds a non-empty goal."""

from typing import Any

from jsonschema import Draft202012Validator
from onolys_core.safe_log import log_event, register_fields
from paudit.pack import Pack

from onolys_evaluation.report import Issue

register_fields({"final", "issues", "no_rating"})

MAX_TEXT = 1000  # reason / note / example text
MAX_NOTES = 3000
_MAX_SEG = 64  # an echoed unknown key is capped; it is a key, never card text

_BY_VALIDATOR = {
    "type": "invalid_type",
    "maxLength": "too_long",
    "minimum": "out_of_range",
    "maximum": "out_of_range",
    "required": "required",
}


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _seg(k: Any) -> str:
    return str(k)[:_MAX_SEG]


def _join(*parts: Any) -> str:
    return "/".join(_seg(p) for p in parts)


def _schema_issues(pack: Pack, obj: dict) -> list[Issue]:
    out: list[Issue] = []
    for e in Draft202012Validator(pack.rating_schema).iter_errors(obj):
        path = [*e.absolute_path]
        if path == ["change_goal"] and e.instance is None:
            continue  # an unset goal is incomplete, not malformed: only final requires it
        if e.validator == "additionalProperties":
            known = e.schema.get("properties", {})
            if isinstance(e.instance, dict):
                out += [Issue(path=_join(*path, k), code="unknown_key")
                        for k in e.instance if k not in known]
            continue
        out.append(Issue(path=_join(*path), code=_BY_VALIDATOR.get(e.validator, "invalid")))
    return out


def _pack_issues(pack: Pack, obj: dict) -> list[Issue]:
    out: list[Issue] = []
    by_kind = {"global": {}, "count": {}}
    for it in pack.items:
        by_kind.get(it["kind"], {})[it["id"]] = it
    for section, kind, field in (("globals", "global", "score"), ("counts", "count", "count")):
        sec = obj.get(section)
        if not isinstance(sec, dict):
            continue
        for k, v in sec.items():
            if k not in by_kind[kind]:
                out.append(Issue(path=_join(section, k), code="unknown_key"))
                continue
            val = v.get(field) if isinstance(v, dict) else None
            if kind == "global" and _int(val):
                scale = by_kind[kind][k].get("scale") or {}
                lo, hi = scale.get("min", val), scale.get("max", val)
                if not lo <= val <= hi:
                    out.append(Issue(path=_join(section, k, field), code="out_of_range"))
            if kind == "count" and _int(val) and val < 0:
                out.append(Issue(path=_join(section, k, field), code="out_of_range"))
            if isinstance(v, dict):
                nf = "note" if kind == "count" else "reason"
                note = v.get(nf)
                if isinstance(note, str) and len(note) > MAX_TEXT:
                    out.append(Issue(path=_join(section, k, nf), code="too_long"))
                ex = v.get("example")
                if isinstance(ex, dict) and isinstance(ex.get("text"), str) \
                        and len(ex["text"]) > MAX_TEXT:
                    out.append(Issue(path=_join(section, k, "example", "text"), code="too_long"))
    notes = obj.get("notes")
    if isinstance(notes, str) and len(notes) > MAX_NOTES:
        out.append(Issue(path="notes", code="too_long"))
    span = obj.get("coded_span")
    if isinstance(span, dict):
        a, b = span.get("from_s"), span.get("to_s")
        for name, v in (("from_s", a), ("to_s", b)):
            if _num(v) and v < 0:
                out.append(Issue(path=_join("coded_span", name), code="out_of_range"))
        if _num(a) and _num(b) and a >= 0 and b >= 0 and a > b:
            out.append(Issue(path="coded_span", code="order"))
    return out


def validate_rating(pack: Pack, obj: Any, final: bool) -> list[Issue]:
    """Issues for a rating card (empty = valid). Draft: shape and limits; final: also `change_goal`.

    A missing item stays null (never defaulted). Use `is_no_rating` for the "no rating" run test.
    """
    if not isinstance(obj, dict):
        issues = [Issue(path="", code="invalid_type")]
    else:
        issues = _schema_issues(pack, obj) + _pack_issues(pack, obj)
        goal = obj.get("change_goal")
        if final and (not isinstance(goal, str) or not goal.strip()):
            issues.append(Issue(path="change_goal", code="required"))
    seen: set[tuple[str, str]] = set()
    unique = []
    for i in issues:
        if (i.path, i.code) not in seen:
            seen.add((i.path, i.code))
            unique.append(i)
    log_event("rating_validated", final=final, issues=len(unique))
    return unique


def is_no_rating(obj: Any) -> bool:
    """True for a card with no score, no count and no non-blank notes (a "no rating" run)."""
    if not isinstance(obj, dict):
        return True
    for section, field in (("globals", "score"), ("counts", "count")):
        sec = obj.get(section)
        if isinstance(sec, dict) and any(
            isinstance(v, dict) and v.get(field) is not None for v in sec.values()
        ):
            return False
    notes = obj.get("notes")
    return not (isinstance(notes, str) and notes.strip())
