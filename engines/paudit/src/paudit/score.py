"""Rules, counts and summaries: "code decides" after the model proposes (PRD R2 steps 6-7).

Protocol-agnostic: everything comes from the pack's `rules[]`, `items[]` and `summaries[]`.
Violations never delete an instance: it stays with `counted=False` and an `uncounted_reason`.
Instances must be given in text order ("first in text order wins").

Reason strings (engine-derived, so packs need not name them):
- `one_code_per_utterance`  -> `second_code_on_utterance`
- `max_per_unit` (volley)   -> `duplicate_in_volley`
- `exclusive_group`         -> `superseded_by_<winning code>`
Hook adjustments carry their own reason.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from paudit.formula import evaluate, label_for
from paudit.hooks import Hooks
from paudit.pack import Pack
from paudit.result import Instance, Reference, ResultWarning, Summary


def _down(inst: Instance, reason: str) -> None:
    inst.counted = False
    inst.uncounted_reason = reason


def _live(instances: Iterable[Instance]) -> list[Instance]:
    return [i for i in instances if i.counted and i.code is not None]


def _one_code_per_utterance(instances: list[Instance]) -> None:
    seen: set[tuple[str, int, int]] = set()
    for i in _live(instances):
        key = (i.turn_id, i.start, i.end)
        if key in seen:
            _down(i, "second_code_on_utterance")
        else:
            seen.add(key)


def _max_per_unit(instances: list[Instance], rule: Mapping[str, Any]) -> None:
    """`code: any` caps each distinct code separately (a volley earns each code once)."""
    n, code = int(rule["n"]), rule["code"]
    taken: dict[tuple[str, str], int] = {}
    for i in _live(instances):
        if code != "any" and i.code != code:
            continue
        key = (i.volley_id, i.code)  # type: ignore[assignment]
        if taken.get(key, 0) >= n:
            _down(i, "duplicate_in_volley")
        else:
            taken[key] = taken.get(key, 0) + 1


def _exclusive_group(instances: list[Instance], rule: Mapping[str, Any]) -> None:
    group = list(rule["codes"])
    precedence = list(rule.get("precedence") or [])
    by_volley: dict[str, list[Instance]] = {}
    for i in _live(instances):
        if i.code in group:
            by_volley.setdefault(i.volley_id, []).append(i)
    for members in by_volley.values():
        present = {m.code for m in members}
        if len(present) < 2:
            continue
        winner = next((c for c in precedence if c in present), members[0].code)
        for m in members:
            if m.code != winner:
                _down(m, f"superseded_by_{winner}")


def _apply_hook(instances: list[Instance], hook: Callable[..., Any], ctx: Any
                ) -> list[ResultWarning]:
    """Hook may only down-count: each adjustment is exactly `{id, uncounted_reason}` for a
    currently counted instance. Anything else (relabel, add, re-count, unknown id) is ignored
    and reported as a `hook_adjustment_ignored` warning."""
    adjustments = hook([i.model_copy(deep=True) for i in instances], ctx) or []
    index = {i.id: i for i in instances}
    warns: list[ResultWarning] = []
    for adj in adjustments:
        ok = (
            isinstance(adj, Mapping)
            and set(adj) == {"id", "uncounted_reason"}
            and isinstance(adj["uncounted_reason"], str)
            and adj["uncounted_reason"].strip() != ""
            and (target := index.get(adj["id"])) is not None
            and target.counted
            and target.code is not None
        )
        if ok:
            _down(target, adj["uncounted_reason"])
        else:
            item = adj.get("id") if isinstance(adj, Mapping) else None
            warns.append(ResultWarning(
                code="hook_adjustment_ignored", severity="info",
                item_id=item if isinstance(item, str) else None,
                detail="validate_codes adjustment is not a down-count of a counted instance",
            ))
    return warns


def apply_rules(
    instances: Sequence[Instance],
    rules: Sequence[Mapping[str, Any]],
    *,
    validate_codes: Callable[..., Any] | None = None,
    ctx: Any = None,
) -> tuple[list[Instance], list[ResultWarning]]:
    """Apply `rules` in order, then the optional `validate_codes` hook. Returns new instances
    (input untouched) in the same order, plus warnings for ignored hook adjustments."""
    out = [i.model_copy(deep=True) for i in instances]
    for rule in rules:
        kind = rule["kind"]
        if kind == "one_code_per_utterance":
            _one_code_per_utterance(out)
        elif kind == "max_per_unit":
            _max_per_unit(out, rule)
        elif kind == "exclusive_group":
            _exclusive_group(out, rule)
        else:
            raise ValueError(f"unknown rule kind: {kind}")
    warns = _apply_hook(out, validate_codes, ctx) if validate_codes else []
    # Re-validate: `counted`/`uncounted_reason` were mutated in place.
    return [Instance.model_validate(i.model_dump()) for i in out], warns


def count_instances(instances: Iterable[Instance], count_ids: Iterable[str]) -> dict[str, int]:
    """Counted instances per count item id (zeros included, in `count_ids` order)."""
    counts = {cid: 0 for cid in count_ids}
    for i in instances:
        if i.counted and i.code in counts:
            counts[i.code] += 1
    return counts


def compute_summaries(
    summaries: Sequence[Mapping[str, Any]],
    counts: Mapping[str, int],
    globals_: Mapping[str, int | float],
    *,
    compute_summary: Callable[..., Any] | None = None,
    ctx: Any = None,
) -> dict[str, Summary]:
    """Evaluate each summary formula over counts + final global scores. Division by zero or a
    missing global gives `value=None`. The optional `compute_summary` hook returns
    `{summary_id: value}` overrides (unknown ids ignored); labels are always recomputed here.
    Summaries without `reference` get label and reference None."""
    values: dict[str, float | int | None] = {**counts, **globals_}
    override: Mapping[str, Any] = {}
    if compute_summary:
        override = compute_summary(dict(counts), dict(globals_), ctx) or {}
    out: dict[str, Summary] = {}
    for s in summaries:
        sid = s["id"]
        value = override[sid] if sid in override else evaluate(s["expr"], values)
        ref = s.get("reference")
        out[sid] = Summary(
            value=None if value is None else float(value),
            label=label_for(None if value is None else float(value), ref),
            reference=Reference(fair=float(ref["fair"]), good=float(ref["good"])) if ref else None,
        )
    return out


def score_run(
    pack: Pack,
    instances: Sequence[Instance],
    globals_: Mapping[str, int | float],
    hooks: Hooks | None = None,
) -> tuple[list[Instance], dict[str, int], dict[str, Summary], list[ResultWarning]]:
    """Rules + hook -> counts -> summaries for one run. `globals_` maps global item id to its
    final score (from the globals pass)."""
    hooks = hooks or Hooks()
    ctx = {"pack": pack.data}
    final, warns = apply_rules(instances, pack.data.get("rules", []),
                               validate_codes=hooks.validate_codes, ctx=ctx)
    count_ids = [i["id"] for i in pack.items if i["kind"] == "count"]
    counts = count_instances(final, count_ids)
    summaries = compute_summaries(pack.data.get("summaries", []), counts, globals_,
                                  compute_summary=hooks.compute_summary, ctx=ctx)
    return final, counts, summaries, warns
