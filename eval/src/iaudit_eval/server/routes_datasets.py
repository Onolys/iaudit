"""Read-mostly dataset routes and explicit download requests."""

from fastapi import APIRouter, Request

from iaudit_eval.server.models import DatasetMeta, DatasetSummary, DownloadStatus

router = APIRouter()


@router.get("/datasets", response_model=list[DatasetSummary])
async def list_datasets(request: Request):
    manager = request.app.state.manager
    result = []
    for dataset in await manager.list_datasets():
        present, sizes = await manager.dataset_sizes(dataset)
        result.append({
            "name": dataset.meta.name,
            "product": dataset.meta.product,
            "title": dataset.meta.title,
            "data_present": present,
            "splits": [{"name": name, "size": sizes[name]} for name in dataset.meta.split_names()],
        })
    return result


@router.get("/datasets/{name}", response_model=DatasetMeta)
async def dataset_meta(name: str, request: Request):
    manager = request.app.state.manager
    dataset = await manager.get_dataset(name)
    _, sizes = await manager.dataset_sizes(dataset)
    meta = dataset.meta.to_dict()
    meta["splits"] = [{**split, "size": sizes[split["name"]]} for split in dataset.meta.splits]
    return meta


@router.post("/datasets/{name}/download", response_model=DownloadStatus, status_code=202)
async def start_download(name: str, request: Request):
    manager = request.app.state.manager
    return await manager.start_download(await manager.get_dataset(name))


@router.get("/datasets/{name}/download", response_model=DownloadStatus)
async def download_status(name: str, request: Request):
    manager = request.app.state.manager
    return await manager.download_status(await manager.get_dataset(name))
