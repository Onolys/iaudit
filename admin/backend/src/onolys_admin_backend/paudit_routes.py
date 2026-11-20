"""Admin-only paudit routes: POST /v1/paudit and GET /v1/paudit/fixtures[/{name}].

Registered on the parent app before eaudit is mounted at "/", behind the same auth middleware.
Nothing is stored and no transcript text is logged (ids, counts and statuses only, through
`onolys_core.safe_log`). Error bodies reuse eaudit's contract-style shape.

Deadline: the run is an asyncio task awaited with `asyncio.wait_for(ADMIN_PAUDIT_DEADLINE_S)`.
paudit and the LLM client are async, so a timeout cancels the whole run (pending model calls
included) and frees the server; no worker thread is left behind. The trade-off versus a worker
thread: CPU-bound steps (prepare, scoring) run on the event loop; they are small next to the
model calls. A model call that is blocked in non-async code could not be interrupted, but the
shared client is async.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from eaudit.api.errors import ApiError, error_body, log_exception
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from onolys_core import InputError, OnolysError
from onolys_core.llm import LLMClient, LLMConfig, LLMUnavailable, MetricsCollector, make_client
from onolys_core.safe_log import log_event, register_fields
from onolys_core.transcript import Transcript
from paudit.engine import AllRunsFailed, run
from paudit.pack import Pack, load_pack
from pydantic import ValidationError

PACK_REF = "miti@4.2.1"
DEFAULT_DEADLINE_S = 100.0
DEFAULT_MAX_BODY_BYTES = 2_000_000  # eaudit's Settings.max_body_bytes default
MAX_N_RUNS = 5
_PARAM_KEYS = ("speaker_map", "change_goal", "coded_span", "language", "n_runs")

register_fields({"body_bytes", "turns"})
log = logging.getLogger("iaudit")


def _err(status: int, message: str, code: str, detail: str | None = None, rid=None) -> ApiError:
    return ApiError(status, message, [{"code": code, "message": detail or message}], rid)


def _bad(message: str, code: str = "invalid_parameters", detail: str | None = None) -> ApiError:
    return _err(400, message, code, detail)


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _validate_params(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _bad("Request rejected: params must be an object.", "missing_parameter", "params")
    sm = raw.get("speaker_map")
    if not isinstance(sm, dict) or not _nonempty_str(sm.get("subject")):
        raise _bad(
            "Request rejected: params.speaker_map.subject is required.",
            "missing_parameter",
            "params.speaker_map.subject: required",
        )
    if not _nonempty_str(raw.get("change_goal")):
        raise _bad(
            "Request rejected: params.change_goal is required.",
            "missing_parameter",
            "params.change_goal: required",
        )
    out: dict[str, Any] = {k: raw[k] for k in _PARAM_KEYS if raw.get(k) is not None}
    span = out.get("coded_span")
    if span is not None:
        ok = (
            isinstance(span, dict)
            and set(span) <= {"from_s", "to_s"}
            and all(
                isinstance(span.get(k), int | float) and not isinstance(span.get(k), bool)
                for k in ("from_s", "to_s")
            )
            and span["from_s"] <= span["to_s"]
        )
        if not ok:
            raise _bad(
                "Request rejected: invalid parameters.",
                detail="params.coded_span: must be {from_s, to_s} with from_s <= to_s",
            )
    if "language" in out and not isinstance(out["language"], str):
        raise _bad("Request rejected: invalid parameters.", detail="params.language: not a string")
    if "n_runs" in out:
        n = out["n_runs"]
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_N_RUNS:
            raise _bad(
                "Request rejected: invalid parameters.",
                detail=f"params.n_runs: must be an integer from 1 to {MAX_N_RUNS}",
            )
    return out


def _paths(exc: ValidationError) -> str:
    # paths only: pydantic messages can embed input values (transcript text)
    return "; ".join(
        ".".join(["transcript", *(str(p) for p in e["loc"])]) + ": invalid"
        for e in exc.errors()[:5]
    )


async def _read_body(request: Request, limit: int, info: dict) -> bytes:
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media and media != "application/json":
        raise _err(
            415,
            "Request rejected: wrong content type.",
            "unsupported_media_type",
            "Content-Type must be application/json.",
        )
    too_large = _err(413, "Request too large.", "body_too_large", "Request body is too large.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_large
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():  # stop reading as soon as the cap is passed
        size += len(chunk)
        if size > limit:
            info["body_bytes"] = size
            raise too_large
        chunks.append(chunk)
    info["body_bytes"] = size
    return b"".join(chunks)


def _fixtures_dir(pack: Pack) -> Path:
    return pack.root / "fixtures"


def _fixture(pack: Pack, name: str) -> dict[str, Any] | None:
    """One synthetic fixture with its ready-to-run params, or None. `name` is matched against
    the directory listing, never joined into a path, so it cannot escape the fixtures folder."""
    base = _fixtures_dir(pack)
    for p in sorted(base.glob("*.params.json")):
        stem = p.name.removesuffix(".params.json")
        tpath = base / f"{stem}.json"
        if stem != name or not tpath.is_file():
            continue
        transcript = json.loads(tpath.read_text(encoding="utf-8"))
        if transcript.get("synthetic") is not True:
            return None
        return {
            "name": stem,
            "description": transcript.get("description", ""),
            "pack": PACK_REF,
            "transcript": transcript,
            "params": json.loads(p.read_text(encoding="utf-8")),
        }
    return None


def _fixture_names(pack: Pack) -> list[str]:
    base = _fixtures_dir(pack)
    names = [p.name.removesuffix(".params.json") for p in sorted(base.glob("*.params.json"))]
    return [n for n in names if _fixture(pack, n) is not None]


def register_paudit_routes(
    app: FastAPI,
    env: Mapping[str, str],
    client: LLMClient | None = None,
    client_factory: Callable[[], LLMClient] | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> None:
    deadline_s = float(env.get("ADMIN_PAUDIT_DEADLINE_S") or DEFAULT_DEADLINE_S)
    state: dict[str, Any] = {"client": client, "pack": None}

    def get_pack() -> Pack:
        if state["pack"] is None:
            state["pack"] = load_pack(PACK_REF)
        return state["pack"]

    def get_client() -> LLMClient:
        if state["client"] is None:  # lazy: a missing key must not fail startup
            factory = client_factory or (lambda: make_client(LLMConfig(llm_mode="live")))
            state["client"] = factory()
        return state["client"]

    def error_response(exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=error_body(exc.status, exc.message, exc.details, exc.request_id),
        )

    @app.get("/v1/paudit/fixtures")
    async def list_fixtures():
        pack = get_pack()
        items = []
        for n in _fixture_names(pack):
            f = _fixture(pack, n)
            items.append(
                {
                    "name": n,
                    "description": f["description"],
                    "pack": PACK_REF,
                    "turns": len(f["transcript"].get("turns", [])),
                    "params": f["params"],
                }
            )
        return {"pack": PACK_REF, "fixtures": items}

    @app.get("/v1/paudit/fixtures/{name}")
    async def get_fixture(name: str):
        f = _fixture(get_pack(), name)
        if f is None:
            return error_response(_err(404, "Fixture not found.", "not_found", "No such fixture."))
        return f

    @app.post("/v1/paudit")
    async def paudit_run(request: Request):
        started = time.monotonic()
        info: dict[str, Any] = {}
        status, outcome = 200, "ok"
        try:
            return await _paudit(request, info)
        except ApiError as exc:
            status, outcome = exc.status, exc.details[0]["code"]
            return error_response(exc)
        finally:
            log_event(
                "paudit_request",
                status=status,
                outcome=outcome,
                total_ms=round((time.monotonic() - started) * 1000),
                **info,
            )

    async def _paudit(request: Request, info: dict):
        body = await _read_body(request, max_body_bytes, info)
        try:
            raw = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise _err(
                400,
                "Request rejected: the file is not valid JSON.",
                "invalid_json",
                "Body is not valid JSON.",
            ) from None
        if not isinstance(raw, dict):
            raise _err(
                400,
                "Request rejected: the file is not valid JSON.",
                "invalid_json",
                "Body must be a JSON object.",
            )
        rid = raw.get("request_id")
        request_id = rid if isinstance(rid, str) and rid else str(uuid.uuid4())
        info["request_id"] = request_id
        try:
            if raw.get("pack") != PACK_REF:
                raise _bad(
                    "Request rejected: unknown pack.", "unknown_pack", f'pack: must be "{PACK_REF}"'
                )
            params = _validate_params(raw.get("params"))
            try:
                transcript = Transcript.model_validate(raw.get("transcript"))
            except ValidationError as exc:
                raise _bad(
                    "The request does not match the paudit contract.",
                    "schema_violation",
                    _paths(exc),
                ) from None
            if not transcript.turns:
                raise _bad("Request rejected: the transcript has no turns.", "empty_transcript")
            info["turns"] = len(transcript.turns)
            info["speakers"] = len({t.speaker for t in transcript.turns})
            if params.get("n_runs"):
                info["n_runs"] = params["n_runs"]

            metrics = MetricsCollector()
            result = await asyncio.wait_for(
                run(
                    transcript,
                    get_pack(),
                    params,
                    get_client(),
                    metrics=metrics,
                    request_id=request_id,
                ),
                timeout=deadline_s,
            )
            snap = metrics.snapshot()
            info["calls"] = snap["calls"]
            return JSONResponse(json.loads(result.model_dump_json()))
        except ApiError as exc:
            exc.request_id = exc.request_id or request_id
            raise
        except InputError as exc:
            raise _err(400, "Request rejected.", "input_rejected", str(exc), request_id) from None
        except LLMUnavailable:
            raise _err(
                503,
                "Audit service temporarily unavailable.",
                "upstream_unavailable",
                rid=request_id,
            ) from None
        except TimeoutError:
            raise _err(
                504, "The audit ran out of time.", "deadline_exceeded", rid=request_id
            ) from None
        except AllRunsFailed:
            raise _err(
                502, "The protocol audit failed.", "run_failed", "Every run failed.", request_id
            ) from None
        except OnolysError as exc:
            log_exception(exc)
            raise _err(500, "Internal server error.", "internal_error", rid=request_id) from None
        except Exception as exc:
            log_exception(exc)
            raise _err(500, "Internal server error.", "internal_error", rid=request_id) from None
