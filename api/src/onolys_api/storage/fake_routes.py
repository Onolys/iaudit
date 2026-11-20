"""Routes that serve the FakeBlobStore's signed URLs (mounted only for a FakeBlobStore)."""

from fastapi import APIRouter, HTTPException, Request, Response

from onolys_api.storage.fake import FAKE_ROUTE, FakeBlobStore


def make_fake_blob_router(store: FakeBlobStore) -> APIRouter:
    router = APIRouter(prefix=FAKE_ROUTE, include_in_schema=False)

    def _check(method: str, key: str, m: str, exp: int, ct: str, max_: int, sig: str) -> None:
        if m != method or not store.verify(method, key, exp, ct, max_, sig):
            raise HTTPException(403)

    @router.put("/{key:path}")
    async def put_blob(
        key: str,
        request: Request,
        m: str,
        exp: int,
        sig: str,
        ct: str = "",
        max: int = 0,  # noqa: A002
    ) -> Response:
        _check("PUT", key, m, exp, ct, max, sig)
        if request.headers.get("content-type", "") != ct:
            raise HTTPException(403)
        body = await request.body()
        if len(body) > max:
            raise HTTPException(403)
        store.put_bytes(key, body, ct)
        return Response(status_code=200)

    @router.get("/{key:path}")
    async def get_blob(key: str, m: str, exp: int, sig: str) -> Response:
        _check("GET", key, m, exp, "", 0, sig)
        try:
            data = store.get_bytes(key)
        except Exception:
            raise HTTPException(404) from None
        return Response(content=data, media_type="application/octet-stream")

    return router
