"""Health polling does not invoke an audit or a version-probe POST."""

from importlib.metadata import version

from fastapi import APIRouter, Request

from iaudit_eval.server.models import Health

router = APIRouter()
EVAL_API_VERSION = version("iaudit-eval")


@router.get("/health", response_model=Health)
async def health(request: Request):
    reachable = await request.app.state.backend_client.healthz()
    return {
        "status": "ok",
        "eval_api_version": EVAL_API_VERSION,
        "backend": {
            "url": request.app.state.settings.backend_url,
            "reachable": reachable,
            # The backend's /healthz and B2's healthz() expose no schema version.
            "schema_version": None,
        },
    }
