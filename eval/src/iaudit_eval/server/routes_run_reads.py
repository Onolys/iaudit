"""Run reads and comparisons; all disk/adapter/scoring work stays off the HTTP loop."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query, Request

from iaudit_eval.server.models import ItemDetail, ItemFilter, ItemPage, RunDetail, RunSummary

router = APIRouter()


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(request: Request):
    return await asyncio.to_thread(request.app.state.reader.list_runs)


@router.get("/runs/{id}", response_model=RunDetail)
async def detail(id: str, request: Request):
    return await asyncio.to_thread(request.app.state.reader.detail, id)


@router.get("/runs/{id}/metrics")
async def metrics(id: str, request: Request):
    return await asyncio.to_thread(request.app.state.reader.metrics, id)


@router.get("/runs/{id}/items", response_model=ItemPage)
async def items(
    id: str, request: Request, filter: ItemFilter = "all",
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await asyncio.to_thread(
        request.app.state.reader.items, id, filter=filter, limit=limit, offset=offset,
    )


@router.get("/runs/{id}/items/{item_id}", response_model=ItemDetail)
async def item_detail(id: str, item_id: str, request: Request):
    return await asyncio.to_thread(request.app.state.reader.item_detail, id, item_id)


@router.get("/compare")
async def compare(request: Request, a: str, b: str):
    return await asyncio.to_thread(request.app.state.reader.compare, a, b)
