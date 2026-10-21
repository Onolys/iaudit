"""Explicit, guarded run mutations; business logic belongs to RunManager."""

from fastapi import APIRouter, Request

from iaudit_eval.server.models import (
    Estimate,
    EstimateRequest,
    ResumeRequest,
    RunCreated,
    RunRequest,
    RunSummary,
)

router = APIRouter()


@router.post("/runs/estimate", response_model=Estimate)
async def estimate(payload: EstimateRequest, request: Request):
    return await request.app.state.manager.estimate(payload)


@router.post("/runs", response_model=RunCreated, status_code=202)
async def start(payload: RunRequest, request: Request):
    return await request.app.state.manager.start(payload)


@router.post("/runs/{id}/abort", response_model=RunSummary)
async def abort(id: str, request: Request):
    return await request.app.state.manager.abort(id)


@router.post("/runs/{id}/resume", response_model=RunSummary)
async def resume(id: str, request: Request, payload: ResumeRequest | None = None):
    fields = payload.model_fields_set if payload is not None else set()
    cap = {"max_cost_usd": payload.max_cost_usd} if "max_cost_usd" in fields else {}
    return await request.app.state.manager.resume(id, **cap)


@router.post("/runs/{id}/rescore", response_model=RunSummary, status_code=202)
async def rescore(id: str, request: Request):
    return await request.app.state.manager.rescore(id)
