"""Globals pass (PRD R2 step 8, Decisions 6-9): one call rates every global item of the pack.

The model sees the selected span (turn ids and text), the change goal and the pack's global
definitions, never counts. It returns per global a score, a reason, evidence quotes and
`poor_practice_cited`. Code then: locates each quote in its turn (code-point offsets; unlocatable
ones are dropped with `quote_not_found`), errors on an out-of-scale score, resets to the scale
default with `insufficient_evidence` when fewer than `evidence_min` quotes were located, and
applies a pack cap only where the item declares `caps[]` (`source: "capped"`, `raw_score` kept).
A truncated or invalid response (`LLMBadOutput`) is retried once, then the run fails.

Token limits, timeouts, sampling and model choice belong to the route (core); the request carries
only the engine default (or the pack's `params.globals_max_tokens`), which core clamps.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from onolys_core.errors import OnolysError
from onolys_core.llm import LLMBadOutput, LLMClient, LLMRequest, MetricsCollector
from onolys_core.locate import locate
from pydantic import BaseModel, create_model

from paudit.code_pass import _CFG
from paudit.pack import Pack
from paudit.prepare import Prepared
from paudit.result import Evidence, GlobalScore, ResultWarning

ROUTE = "paudit_globals"
DEFAULT_GLOBALS_MAX_TOKENS = 4000
CAP_WHEN_POOR_PRACTICE = "poor_practice_cited"

_OUTPUT_FORMAT = (
    "## Output format\n"
    'Reply with JSON only: {"globals": {"<id>": {"score": <integer on the scale>, '
    '"reason": "...", "evidence": [{"turn_id": "...", "quote": "..."}], '
    '"poor_practice_cited": [{"turn_id": "...", "quote": "..."}]}}}.\n'
    "Include every global id. Each `quote` is copied verbatim from one turn and never spans two "
    "turns. Use empty lists when there is nothing to cite."
)


class GlobalsPassFailed(OnolysError):
    """The globals pass cannot produce trustworthy output: invalid or truncated output after one
    retry, or a score outside the item's scale. The run fails (ADR 0012)."""

    code = "run_failed"


@dataclass
class GlobalsResult:
    globals: dict[str, GlobalScore] = field(default_factory=dict)
    warnings: list[ResultWarning] = field(default_factory=list)


def global_items(pack: Pack) -> list[dict[str, Any]]:
    return [i for i in pack.items if i["kind"] == "global"]


def make_response_model(ids: list[str]) -> type[BaseModel]:
    """Response model with one required entry per global id."""
    cited = create_model("Cited", turn_id=(str, ...), quote=(str, ...))
    one = create_model(
        "GlobalRating",
        score=(int, ...),
        reason=(str, ...),
        evidence=(list[cited], ...),  # type: ignore[valid-type]
        poor_practice_cited=(list[cited], ...),  # type: ignore[valid-type]
    )
    holder = create_model("Globals", **{i: (one, ...) for i in ids})  # type: ignore[call-overload]
    return create_model("GlobalsResponse", globals=(holder, ...))


def _render_definitions(pack: Pack) -> str:
    lines = ["## Globals"]
    for item in global_items(pack):
        s = item["scale"]
        lines.append(
            f"- {item['id']} ({item['label']}), scale {s['min']}-{s['max']}, default "
            f"{s['default']}: {' '.join(item['definition'].split())}"
        )
    return "\n".join(lines)


def _render_fewshot(pack: Pack) -> str:
    raw = json.loads(pack.prompt_paths[3].read_text(encoding="utf-8"))
    blocks = []
    for n, ex in enumerate(raw, 1):
        if not isinstance(ex, dict) or "input" not in ex or "output" not in ex:
            continue
        inp = json.dumps(ex["input"], ensure_ascii=False, indent=2)
        out = json.dumps(ex["output"], ensure_ascii=False, indent=2)
        blocks.append(f"### Example {n}\nInput:\n{inp}\nOutput:\n{out}")
    return ("## Examples\n" + "\n\n".join(blocks)) if blocks else ""


def _build_request(
    pack: Pack,
    prepared: Prepared,
    params: dict[str, Any],
    language: str | None,
    run_index: int,
    tag: str,
    model: type[BaseModel],
) -> LLMRequest:
    pp = pack.data.get("params", {})
    system_md = pack.prompt_paths[2].read_text(encoding="utf-8").strip()
    prefix1 = "\n\n".join(
        p
        for p in (system_md, _render_definitions(pack), _render_fewshot(pack), _OUTPUT_FORMAT)
        if p
    )
    header = ["## Session", f"Transcript language: {language or 'unspecified'}"]
    header.append("Quotes stay in the transcript's language; reasons are in English.")
    roles = pack.data.get("speaker_roles", {})
    user = {
        "change_goal": params.get("change_goal"),
        "turns": [
            {
                "turn_id": rt.turn.id,
                "speaker": roles.get(rt.role, rt.role),
                "text": rt.turn.text,
            }
            for rt in prepared.turns
        ],
    }
    return LLMRequest(
        tier=ROUTE,
        system="Rate the globals for the span in the user message.",
        user=json.dumps(user, ensure_ascii=False),
        response_model=model,
        call_tag=f"{ROUTE}:r{run_index}:{tag}",
        cache_prefixes=[prefix1, "\n".join(header)],
        unit="globals",
        max_tokens=int(pp.get("globals_max_tokens", DEFAULT_GLOBALS_MAX_TOKENS)),
    )


def _locate_all(
    item_id: str, cited: list[Any], prepared: Prepared, warnings: list[ResultWarning]
) -> list[Evidence]:
    by_id = {rt.turn.id: rt.turn for rt in prepared.turns}
    out: list[Evidence] = []
    for c in cited:
        turn = by_id.get(c.turn_id)
        m = locate(turn.text, c.quote, None, _CFG) if turn is not None else None
        if turn is None or m is None:
            warnings.append(
                ResultWarning(
                    code="quote_not_found",
                    item_id=item_id,
                    detail=f"{c.turn_id}: evidence quote dropped",
                )
            )
            continue
        out.append(
            Evidence(turn_id=turn.id, start=m.start, end=m.end, quote=turn.text[m.start : m.end])
        )
    return out


def _cap_for(item: dict[str, Any], score: int, poor_cited: bool) -> int | None:
    """Lowest applicable cap below `score`, or None. Only the item's own `caps[]` count."""
    maxes = [
        c["max"]
        for c in item.get("caps", [])
        if c["when"] == CAP_WHEN_POOR_PRACTICE and poor_cited and score > c["max"]
    ]
    return min(maxes) if maxes else None


def _rate(item: dict[str, Any], rating: Any, prepared: Prepared, out: GlobalsResult) -> None:
    iid, scale = item["id"], item["scale"]
    raw = rating.score
    if not scale["min"] <= raw <= scale["max"]:
        raise GlobalsPassFailed(
            f"global {iid}: score {raw} outside scale {scale['min']}-{scale['max']}"
        )
    evidence = _locate_all(iid, rating.evidence, prepared, out.warnings)
    need = int(item.get("evidence_min", 0))
    if len(evidence) < need:
        out.warnings.append(
            ResultWarning(
                code="insufficient_evidence",
                item_id=iid,
                detail=f"{len(evidence)} located evidence quote(s), {need} required; "
                f"reset to default {scale['default']}",
            )
        )
        out.globals[iid] = GlobalScore(
            score=scale["default"],
            source="default",
            raw_score=raw,
            reason=rating.reason,
            evidence=[],
        )
        return
    poor = bool(_locate_all(iid, rating.poor_practice_cited, prepared, out.warnings))
    cap = _cap_for(item, raw, poor)
    score, source = (raw, "model") if cap is None else (cap, "capped")
    if cap is not None:
        out.warnings.append(
            ResultWarning(
                code="capped",
                severity="info",
                item_id=iid,
                detail=f"score {raw} capped to {cap}: poor practice cited",
            )
        )
    out.globals[iid] = GlobalScore(
        score=score, source=source, raw_score=raw, reason=rating.reason, evidence=evidence
    )


async def globals_pass(
    client: LLMClient,
    pack: Pack,
    prepared: Prepared,
    params: dict[str, Any],
    *,
    language: str | None = None,
    run_index: int = 0,
    metrics: MetricsCollector | None = None,
) -> GlobalsResult:
    """Run the globals pass for one run. Raises `GlobalsPassFailed` when it cannot be trusted."""
    items = global_items(pack)
    if not items:
        return GlobalsResult()
    model = make_response_model([i["id"] for i in items])
    res = None
    for attempt in (1, 2):
        tag = "g" if attempt == 1 else "g-retry"
        req = _build_request(pack, prepared, params, language, run_index, tag, model)
        try:
            res = await client.complete_json(req, metrics)
            break
        except LLMBadOutput as exc:
            if attempt == 2:
                raise GlobalsPassFailed(
                    "globals: invalid or truncated model output after one retry"
                ) from exc
    assert res is not None
    out = GlobalsResult()
    for item in items:
        _rate(item, getattr(res.parsed.globals, item["id"]), prepared, out)
    return out
