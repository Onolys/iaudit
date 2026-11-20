"""Code pass (PRD R2 steps 4-5): the model proposes utterances and codes, code verifies them.

Volleys are sent in batches of `volleys_per_call` on the `paudit_code` route. The first batch goes
alone (core `warm_then_fanout`) so later batches can read the prompt cache. A truncated or
invalid response (`LLMBadOutput`) halves the batch and retries each half once. Each quote is
located inside its volley's turn text; unlocatable or overlapping utterances are dropped with a
warning. More than 20% dropped retries the batch once, then the run fails: no silent partial
counts. Rules and scoring run afterwards (`paudit.score`).

Token limits, timeouts, sampling and model choice belong to the route (core); the request only
carries the engine default (or the pack's `params` override), which core clamps to the route.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from onolys_core.errors import OnolysError
from onolys_core.llm import LLMBadOutput, LLMClient, LLMRequest, MetricsCollector
from onolys_core.llm.warm import warm_then_fanout
from onolys_core.locate import locate
from onolys_core.transcript import Turn
from pydantic import BaseModel, create_model

from paudit.pack import Pack
from paudit.prepare import Prepared, Volley
from paudit.result import Instance, ResultWarning

ROUTE = "paudit_code"
DEFAULT_VOLLEYS_PER_CALL = 25
DEFAULT_CODE_MAX_TOKENS = 8000
MAX_DROP_RATE = 0.20  # a batch with a larger share of dropped utterances is retried once
UNCODED = "uncoded"

_OUTPUT_FORMAT = (
    "## Output format\n"
    'Reply with JSON only: {"volleys": [{"volley_id": "...", "utterances": '
    '[{"quote": "...", "code": "<code id or null>", "rationale": "..."}]}]}.\n'
    "Return one entry per volley you were given, with utterances in text order. `quote` is "
    "copied verbatim from one clinician turn and never spans two turns. Use null for an "
    "utterance that earns no code."
)


class CodePassFailed(OnolysError):
    """The code pass cannot produce trustworthy output: a batch stayed invalid after halving or
    kept dropping more than 20% of its utterances after one retry. The run fails (ADR 0012)."""

    code = "run_failed"


@dataclass(frozen=True)
class _LocateCfg:
    fuzzy_threshold: float = 90
    fuzzy_min_len: int = 12


_CFG = _LocateCfg()


@dataclass
class CodePassResult:
    instances: list[Instance] = field(default_factory=list)
    warnings: list[ResultWarning] = field(default_factory=list)


@dataclass(frozen=True)
class RequestParts:
    cache_prefixes: list[str]
    system: str
    max_tokens: int
    volleys_per_call: int
    response_model: type[BaseModel]


def count_codes(pack: Pack) -> list[str]:
    return [i["id"] for i in pack.items if i["kind"] == "count"]


def make_response_model(codes: list[str]) -> type[BaseModel]:
    """Response model whose `code` enum is the pack's count ids (or null for uncoded)."""
    code_type = Literal[tuple(codes)] | None  # type: ignore[valid-type]
    utterance = create_model(
        "Utterance", quote=(str, ...), code=(code_type, ...), rationale=(str, ...)
    )
    volley = create_model(
        "VolleyCodes",
        volley_id=(str, ...),
        utterances=(list[utterance], ...),  # type: ignore[valid-type]
    )
    return create_model("CodeResponse", volleys=(list[volley], ...))  # type: ignore[valid-type]


def _render_definitions(pack: Pack) -> str:
    lines = ["## Codes"]
    for item in pack.items:
        if item["kind"] != "count":
            continue
        lines.append(f"- {item['id']} ({item['label']}): {' '.join(item['definition'].split())}")
        for ex in item.get("examples", []):
            lines.append(f'    - example: "{ex}"')
    return "\n".join(lines)


def _render_fewshot(pack: Pack) -> str:
    raw = json.loads(pack.prompt_paths[1].read_text(encoding="utf-8"))
    blocks = []
    for n, ex in enumerate(raw, 1):
        if not isinstance(ex, dict) or "input" not in ex or "output" not in ex:
            continue
        inp = json.dumps({"volleys": [ex["input"]]}, ensure_ascii=False, indent=2)
        out = json.dumps({"volleys": [ex["output"]]}, ensure_ascii=False, indent=2)
        blocks.append(f"### Example {n}\nInput:\n{inp}\nOutput:\n{out}")
    return ("## Examples\n" + "\n\n".join(blocks)) if blocks else ""


_PARAM_KEYS = ("volleys_per_call", "code_max_tokens", "globals_max_tokens")


def _overrides(params: dict[str, Any]) -> dict[str, Any]:
    """Run params beat pack `params`, which beat the engine defaults (PRD R2)."""
    return {k: params[k] for k in _PARAM_KEYS if params.get(k) is not None}


def build_requests_parts(
    pack: Pack, params: dict[str, Any], language: str | None = None
) -> RequestParts:
    """Everything shared by all batches of a run (so cache prefixes are byte-identical)."""
    pp = {**pack.data.get("params", {}), **_overrides(params)}
    system_md = pack.prompt_paths[0].read_text(encoding="utf-8").strip()
    prefix1 = "\n\n".join(
        p
        for p in (system_md, _render_definitions(pack), _render_fewshot(pack), _OUTPUT_FORMAT)
        if p
    )
    header = ["## Session", f"Transcript language: {language or 'unspecified'}"]
    if params.get("change_goal"):
        header.append(f"Change goal: {params['change_goal']}")
    header.append("Quotes stay in the transcript's language; rationales are in English.")
    return RequestParts(
        cache_prefixes=[prefix1, "\n".join(header)],
        system="Code the clinician volleys in the user message.",
        max_tokens=int(pp.get("code_max_tokens", DEFAULT_CODE_MAX_TOKENS)),
        volleys_per_call=int(pp.get("volleys_per_call", DEFAULT_VOLLEYS_PER_CALL)),
        response_model=make_response_model(count_codes(pack)),
    )


def _render_batch(batch: list[Volley]) -> str:
    return json.dumps(
        {
            "volleys": [
                {
                    "volley_id": v.id,
                    "previous_other_turn": v.prev_other.text if v.prev_other else None,
                    "clinician_turns": [{"turn_id": t.id, "text": t.text} for t in v.turns],
                }
                for v in batch
            ]
        },
        ensure_ascii=False,
    )


@dataclass
class _Attempt:
    # per volley id: located instances (without final ids) in text order
    by_volley: dict[str, list[Instance]]
    warnings: list[ResultWarning]
    total: int
    dropped: int


def _locate_volley(
    volley: Volley, utterances: list[Any]
) -> tuple[list[Instance], list[ResultWarning]]:
    """Locate utterances in text order inside the volley's turns, never across a turn boundary."""
    out: list[Instance] = []
    warns: list[ResultWarning] = []
    ti, cursor = 0, 0  # current turn index and end of the previous utterance in it
    for u in utterances:
        found: tuple[int, int, int] | None = None  # turn index, start, end
        for j in range(ti, len(volley.turns)):
            base = cursor if j == ti else 0
            m = locate(volley.turns[j].text[base:], u.quote, None, _CFG)
            if m is not None:
                found = (j, base + m.start, base + m.end)
                break
        if found is None:
            seen_earlier = any(
                locate(t.text, u.quote, None, _CFG) is not None for t in volley.turns
            )
            code = "overlap" if seen_earlier else "quote_not_found"
            warns.append(ResultWarning(code=code, detail=f"{volley.id}: utterance dropped"))
            continue
        j, start, end = found
        turn: Turn = volley.turns[j]
        ti, cursor = j, end
        coded = u.code is not None
        out.append(
            Instance(
                id="",
                volley_id=volley.id,
                turn_id=turn.id,
                start=start,
                end=end,
                start_ms=turn.start_ms,
                end_ms=turn.end_ms,
                quote=turn.text[start:end],
                code=u.code,
                counted=coded,
                uncounted_reason=None if coded else UNCODED,
                rationale=u.rationale,
            )
        )
    return out, warns


class _Pass:
    def __init__(
        self,
        client: LLMClient,
        parts: RequestParts,
        run_index: int,
        metrics: MetricsCollector | None,
    ) -> None:
        self.client, self.parts, self.run_index, self.metrics = client, parts, run_index, metrics

    async def _attempt(self, batch: list[Volley], tag: str) -> _Attempt:
        req = LLMRequest(
            tier=ROUTE,
            system=self.parts.system,
            user=_render_batch(batch),
            response_model=self.parts.response_model,
            call_tag=f"{ROUTE}:r{self.run_index}:{tag}",
            cache_prefixes=list(self.parts.cache_prefixes),
            unit=f"{batch[0].id}-{batch[-1].id}",
            max_tokens=self.parts.max_tokens,
        )
        res = await self.client.complete_json(req, self.metrics)
        by_id = {v.id: v for v in batch}
        by_volley: dict[str, list[Instance]] = {}
        warnings: list[ResultWarning] = []
        total = dropped = 0
        for vo in res.parsed.volleys:
            total += len(vo.utterances)
            volley = by_id.get(vo.volley_id)
            if volley is None:  # unknown volley id: nothing to anchor to
                dropped += len(vo.utterances)
                warnings += [
                    ResultWarning(code="quote_not_found", detail=f"{vo.volley_id}: unknown volley")
                ] * len(vo.utterances)
                continue
            insts, warns = _locate_volley(volley, vo.utterances)
            by_volley.setdefault(volley.id, []).extend(insts)
            warnings += warns
            dropped += len(warns)
        return _Attempt(by_volley, warnings, total, dropped)

    async def _checked(self, batch: list[Volley], tag: str) -> _Attempt:
        """One call; over 20% dropped -> one more call of the same batch; still over -> fail."""
        for attempt in (1, 2):
            a = await self._attempt(batch, tag if attempt == 1 else f"{tag}-retry")
            if a.total == 0 or a.dropped / a.total <= MAX_DROP_RATE:
                return a
        raise CodePassFailed(
            f"batch {batch[0].id}-{batch[-1].id}: {a.dropped} of {a.total} utterances dropped "
            "after one retry"
        )

    async def batch(self, batch: list[Volley], tag: str) -> list[_Attempt]:
        try:
            return [await self._checked(batch, tag)]
        except LLMBadOutput as exc:
            if len(batch) == 1:  # nothing to halve: retry the single volley once
                return [await self._once(batch, f"{tag}-retry", exc)]
            mid = len(batch) // 2
            return [
                await self._once(batch[:mid], f"{tag}a", exc),
                await self._once(batch[mid:], f"{tag}b", exc),
            ]

    async def _once(self, part: list[Volley], tag: str, first: Exception) -> _Attempt:
        try:
            return await self._checked(part, tag)
        except LLMBadOutput as exc:
            raise CodePassFailed(
                f"batch {part[0].id}-{part[-1].id}: invalid model output after halving"
            ) from exc


async def code_pass(
    client: LLMClient,
    pack: Pack,
    prepared: Prepared,
    params: dict[str, Any],
    *,
    language: str | None = None,
    run_index: int = 0,
    metrics: MetricsCollector | None = None,
    warmed: asyncio.Event | None = None,
) -> CodePassResult:
    """Run the code pass for one run. Raises `CodePassFailed` when the run cannot be trusted.
    `warmed` (optional) is set once the warm (first) batch has returned, so other runs can
    start their own fan-out against a written cache."""
    parts = build_requests_parts(pack, params, language)
    runner = _Pass(client, parts, run_index, metrics)
    size = parts.volleys_per_call
    batches = [prepared.volleys[i : i + size] for i in range(0, len(prepared.volleys), size)]
    if not batches:
        if warmed is not None:
            warmed.set()
        return CodePassResult()
    calls = [(lambda b=b, n=n: runner.batch(b, f"b{n}")) for n, b in enumerate(batches, 1)]

    async def warm_call() -> list[_Attempt]:
        out = await calls[0]()
        if warmed is not None:
            warmed.set()
        return out

    first, rest = await warm_then_fanout(warm_call, calls[1:])
    attempts = [a for group in [first, *rest] for a in group]

    out = CodePassResult()
    by_volley: dict[str, list[Instance]] = {}
    for a in attempts:
        by_volley.update(a.by_volley)
        out.warnings += a.warnings
    n = 0
    for v in prepared.volleys:
        for inst in by_volley.get(v.id, []):
            n += 1
            inst.id = f"i{n}"
            out.instances.append(inst)
    return out
