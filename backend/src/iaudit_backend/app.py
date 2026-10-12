"""FastAPI app: POST /v1/audit, GET /healthz."""

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from iaudit_backend import contract
from iaudit_backend.api.errors import (
    ApiError,
    DeadlineExceeded,
    error_body,
    log_exception,
    register_error_handlers,
)
from iaudit_backend.config import Settings
from iaudit_backend.llm import LLMClient, LLMUnavailable, MetricsCollector, make_client
from iaudit_backend.models import AuditRequest
from iaudit_backend.pipeline import (
    BACKSTOP_GRACE_S,
    Pipeline,
    RequestContext,
    make_pipeline,
    run_with_backstop,
)
from iaudit_backend.safe_log import log_event, setup_logging

log = logging.getLogger("iaudit")
SUPPORTED_VERSION = "1.0.0"
MAX_SAFE_DEADLINE_S = 100
_KEY_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LITELLM_API_KEY")  # presence only


class ContractCORSMiddleware(CORSMiddleware):
    """Disallowed preflights still return a contract error body."""

    def preflight_response(self, request_headers):
        resp = super().preflight_response(request_headers)
        if resp.status_code >= 400:
            return JSONResponse(
                status_code=resp.status_code,
                content=error_body("other", "CORS preflight rejected."),
            )
        return resp


def _count_dupes(items: list[dict]) -> int:
    ids = [i.get("id") for i in items]
    return len(ids) - len(set(ids))


def _server_timing(total_ms: float, pipeline_metrics: dict | None) -> str:
    """Durations only: total plus one entry per pipeline stage (no text, no ids)."""
    parts = [f"total;dur={round(total_ms)}"]
    for stage in ("prep", "atomize", "link", "check", "assemble"):
        ms = (pipeline_metrics or {}).get(f"{stage}_ms")
        if isinstance(ms, int | float):
            parts.append(f"{stage};dur={round(ms)}")
    return ", ".join(parts)


def create_app(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    pipeline: Pipeline | None = None,
    backstop_grace_s: float = BACKSTOP_GRACE_S,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        contract.get_contracts()  # fail fast on a missing or invalid schema
        setup_logging(settings.log_level)
        app.state.llm = llm or make_client(settings)
        app.state.pipeline = pipeline or make_pipeline(settings)
        log.info("startup config=%s", json.dumps(settings.safe_summary(), sort_keys=True))
        if settings.audit_deadline_s > MAX_SAFE_DEADLINE_S:
            log.warning(
                "audit_deadline_s=%s exceeds %s: the cap plus grace and network time may pass "
                "the 120 s client timeout",
                settings.audit_deadline_s,
                MAX_SAFE_DEADLINE_S,
            )
        if settings.llm_mode == "live" and not any(k in os.environ for k in _KEY_VARS):
            log.warning("no provider API key is present; audits will fail with 503 unavailable")
        yield

    app = FastAPI(title="Interview Evidence Auditor", lifespan=lifespan)
    app.state.settings = settings
    register_error_handlers(app)
    app.add_middleware(
        ContractCORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["content-type"],
        allow_credentials=False,
    )

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/v1/audit")
    async def audit(request: Request):
        started = time.monotonic()
        info: dict = {}
        status, outcome = 200, "ok"
        try:
            return await _audit(request, info)
        except ApiError as exc:
            status, outcome = exc.status, exc.code
            raise
        finally:
            metrics = info.pop("metrics", None)
            if metrics is not None:
                snap = metrics.snapshot()
                info["calls"] = snap["calls"]
                info["calls_ok"] = snap["ok"]
                for k in ("input_tokens", "output_tokens", "cache_read_tokens"):
                    info[k] = sum(t[k] for t in snap["by_tier"].values())
                info["models"] = ",".join(sorted({r["model"] for r in snap["records"]}))
            log_event(
                "audit_request",
                status=status,
                outcome=outcome,
                total_ms=round((time.monotonic() - started) * 1000),
                **info,
            )

    async def _audit(request: Request, info: dict):
        request_id: str | None = None
        started = time.monotonic()
        try:
            # 0. content type (a missing header is tolerated; an explicit non-JSON one is not)
            media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if media_type and media_type != "application/json":
                raise ApiError("invalid_request", "Content-Type must be application/json.", 415)
            # 1. body size
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > settings.max_body_bytes:
                raise ApiError("payload_too_large", "Request body is too large.", 413)
            chunks: list[bytes] = []
            size = 0
            async for chunk in request.stream():  # stop reading as soon as the cap is passed
                size += len(chunk)
                if size > settings.max_body_bytes:
                    info["body_bytes"] = size
                    raise ApiError("payload_too_large", "Request body is too large.", 413)
                chunks.append(chunk)
            body = b"".join(chunks)
            info["body_bytes"] = len(body)

            # 2. parse
            try:
                raw = json.loads(body)
            except (ValueError, UnicodeDecodeError, RecursionError):
                raise ApiError("invalid_request", "Body is not valid JSON.", 400) from None
            if not isinstance(raw, dict):
                raise ApiError("invalid_request", "Body must be a JSON object.", 400)
            rid = raw.get("request_id")
            request_id = rid if isinstance(rid, str) and rid else None
            info["request_id"] = request_id
            if isinstance(raw.get("transcript"), list):
                info["turns"] = len(raw["transcript"])
            if isinstance(raw.get("assessment"), list):
                info["sections"] = len(raw["assessment"])

            # 3. version, before schema validation
            if "schema_version" in raw and raw["schema_version"] != SUPPORTED_VERSION:
                raise ApiError(
                    "unsupported_version",
                    f"Only schema_version {SUPPORTED_VERSION} is supported.",
                    400,
                    request_id,
                )

            # 4. cheap size limits on the parsed lists
            transcript, assessment = raw.get("transcript"), raw.get("assessment")
            if isinstance(transcript, list) and len(transcript) > settings.max_turns:
                raise ApiError(
                    "payload_too_large",
                    f"Transcript has more than {settings.max_turns} turns.",
                    413,
                    request_id,
                )
            if isinstance(assessment, list) and len(assessment) > settings.max_sections:
                raise ApiError(
                    "payload_too_large",
                    f"Assessment has more than {settings.max_sections} sections.",
                    413,
                    request_id,
                )

            # 5. schema validation (worker thread: 2 MB bodies would block the loop)
            issues = await run_in_threadpool(contract.validate_request, raw)
            if issues:
                detail = "; ".join(str(i) for i in issues)
                raise ApiError(
                    "invalid_request",
                    f"Request does not match the contract: {detail}",
                    400,
                    request_id,
                )

            # 6. unique ids (count only, never the ids)
            dup_turns, dup_sections = _count_dupes(transcript), _count_dupes(assessment)
            if dup_turns or dup_sections:
                raise ApiError(
                    "invalid_request",
                    f"Duplicate ids: {dup_turns} in transcript, {dup_sections} in assessment.",
                    400,
                    request_id,
                )

            # 7. run
            model = AuditRequest.model_validate(raw)
            ctx = RequestContext(
                settings=settings,
                llm=app.state.llm,
                metrics=MetricsCollector(),
                request_id=request_id,
                deadline=time.monotonic() + settings.audit_deadline_s,
            )
            ctx.extras["audit_uuid"] = info["audit_uuid"] = str(uuid.uuid4())
            info["metrics"] = ctx.metrics
            result = await run_with_backstop(
                app.state.pipeline, model, ctx, settings, grace_s=backstop_grace_s
            )
            out = result.to_json()
            if out.get("request_id") != request_id or contract.validate_response(out):
                raise ApiError("internal_error", "Internal server error.", 500, request_id)
            headers = {}
            if settings.server_timing:
                headers["Server-Timing"] = _server_timing(
                    (time.monotonic() - started) * 1000, ctx.extras.get("pipeline_metrics")
                )
            return JSONResponse(out, headers=headers)
        except ApiError as exc:
            exc.request_id = exc.request_id or request_id
            raise
        except LLMUnavailable:
            raise ApiError(
                "unavailable", "The audit service is temporarily unavailable.", 503, request_id
            ) from None
        except DeadlineExceeded:
            raise ApiError(
                "unavailable", "The audit could not produce a usable result.", 504, request_id
            ) from None
        except Exception as exc:
            log_exception(exc)
            raise ApiError("internal_error", "Internal server error.", 500, request_id) from None

    return app


app = create_app()
