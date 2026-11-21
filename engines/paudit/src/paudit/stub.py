"""Offline stub client driven by a fixtures `expected.yaml` (no model, no network).

For one named fixture it answers the code route with the intended per-utterance codes and the
globals route with the intended scores, evidence and poor-practice quotes. It exists so the
engine, the CLI `run` and the tests are deterministic. It holds no protocol knowledge: ids,
quotes and codes all come from the file.
"""

import json
from pathlib import Path
from typing import Any

import yaml
from onolys_core.llm import FixtureMiss, LLMRequest, LLMResult, MetricsCollector, Usage

from paudit.code_pass import ROUTE as CODE_ROUTE
from paudit.globals_pass import ROUTE as GLOBALS_ROUTE


class ExpectedStubClient:
    def __init__(self, expected_path: str | Path, fixture: str) -> None:
        data = yaml.safe_load(Path(expected_path).read_text(encoding="utf-8"))
        fixtures = data.get("fixtures", {})
        if fixture not in fixtures:
            raise FixtureMiss(f"no fixture named {fixture!r} in {expected_path}")
        self._exp: dict[str, Any] = fixtures[fixture]
        self.requests: list[LLMRequest] = []

    def _code_reply(self, req: LLMRequest) -> dict[str, Any]:
        by_turn: dict[str, list[dict[str, Any]]] = {}
        for u in self._exp["utterances"]:
            by_turn.setdefault(u["turn_id"], []).append(
                {"quote": u["quote"], "code": u["code"], "rationale": u["rationale"]}
            )
        volleys = []
        for v in json.loads(req.user)["volleys"]:
            utterances: list[dict[str, Any]] = []
            for turn in v["clinician_turns"]:
                utterances += by_turn.get(turn["turn_id"], [])
            volleys.append({"volley_id": v["volley_id"], "utterances": utterances})
        return {"volleys": volleys}

    def _globals_reply(self) -> dict[str, Any]:
        out = {}
        for gid, g in self._exp["globals"].items():
            out[gid] = {
                "score": g["score"],
                "reason": g["reason"],
                "evidence": list(g.get("evidence", [])),
                "poor_practice_cited": list(g.get("poor_practice_cited", [])),
            }
        return {"globals": out}

    async def complete_json(
        self, req: LLMRequest, metrics: MetricsCollector | None = None
    ) -> LLMResult:
        self.requests.append(req)
        if req.tier == CODE_ROUTE:
            raw = self._code_reply(req)
        elif req.tier == GLOBALS_ROUTE:
            raw = self._globals_reply()
        else:
            raise FixtureMiss(f"no stub answer for route {req.tier}")
        parsed = req.response_model.model_validate(raw)
        if metrics is not None:
            metrics.record(req, "stub", Usage(), 0.0, 1, True)
        return LLMResult(parsed=parsed, model="stub")
