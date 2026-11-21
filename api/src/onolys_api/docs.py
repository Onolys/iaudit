"""Public docs (R11): `/v1/docs` (Redoc, bundle vendored in `static/`, no external host), the
OpenAPI description with the curl quickstart, and the explicit error responses per operation."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

STATIC = Path(__file__).parent / "static"
REDOC_JS = "/v1/docs/redoc.standalone.js"  # redoc 2.1.5 (MIT), see static/redoc.LICENSE

QUICKSTART = r"""
## Quickstart

Create a session, upload audio, submit the rating card, confirm the speaker, wait for the
report. Every call needs credentials: an `X-API-Key: onolys_<id>_<secret>` header (create a key
in the web app or with `POST /v1/api-key`) or an `Authorization: Bearer <ID token>` header.

```bash
set -euo pipefail
BASE=${BASE:-https://app.onolys.com/v1}
AUTH=${AUTH:-"X-API-Key: onolys_<id>_<secret>"}
AUDIO=${AUDIO:-session.m4a}
JSON='Content-Type: application/json'

# 1. Create the session (the Idempotency-Key makes a retried POST safe for 24 h)
SID=$(curl -sf -X POST "$BASE/sessions" -H "$AUTH" -H "$JSON" \
  -H "Idempotency-Key: quickstart-$(date +%s)-$$" \
  -d '{"language":"auto","n_runs":1,"title":"Quickstart"}' | jq -r .session.id)

# 2. Ask for a signed upload URL, then PUT the file straight to storage
UP=$(curl -sf -X POST "$BASE/sessions/$SID/audio" -H "$AUTH" -H "$JSON" \
  -d "{\"content_type\":\"audio/mp4\",\"size_bytes\":$(wc -c < "$AUDIO" | tr -d ' ')}")
# send every required header (not Host: curl sets it); the signed URL rejects a PUT without them
mapfile -t HDRS < <(echo "$UP" | jq -r '.required_headers | to_entries[]
  | select(.key != "Host") | "-H\n\(.key): \(.value)"')
curl -sf -X PUT "$(echo "$UP" | jq -r .upload_url)" "${HDRS[@]}" --data-binary @"$AUDIO"

# 3. Tell the API the upload is done; validation and transcription start
curl -sf -X POST "$BASE/sessions/$SID/audio/complete" -H "$AUTH" > /dev/null

# wait until the session reaches a status (fails the script on `failed`)
wait_for() {
  for _ in $(seq 1 120); do
    STATUS=$(curl -sf "$BASE/sessions/$SID" -H "$AUTH" | jq -r .status)
    [ "$STATUS" = "$1" ] && return 0
    [ "$STATUS" = "failed" ] && { echo "session failed" >&2; return 1; }
    sleep 1
  done
  echo "timed out waiting for $1" >&2; return 1
}

# 4. Submit the rating card (final=true; use final=false for draft autosaves)
curl -sf -X PUT "$BASE/sessions/$SID/rating" -H "$AUTH" -H "$JSON" \
  -d '{"final":true,"card":{"change_goal":"Reduce evening drinking","notes":"Quickstart"}}' \
  > /dev/null

# 5. Confirm which speaker is the clinician once the transcript is ready
wait_for awaiting_input
CLINICIAN=$(curl -sf "$BASE/sessions/$SID/speakers" -H "$AUTH" | jq -r '.speakers[0].speaker')
curl -sf -X POST "$BASE/sessions/$SID/speakers/confirm" -H "$AUTH" -H "$JSON" \
  -d "{\"clinician_speaker\":\"$CLINICIAN\"}" > /dev/null

# 6. Poll the session, then fetch the report
wait_for report_ready
VERSION=$(curl -sf "$BASE/sessions/$SID" -H "$AUTH" | jq -r .latest_report_version)
curl -sf "$BASE/sessions/$SID/reports/$VERSION" -H "$AUTH" | jq -c .
```

Errors share one body (`ErrorResponse`): `status`, `message`, `details[]` with a stable `code`
(and, for `rating_invalid`, the card `field` path). Mutations return `202` immediately; the
session `status` moves `created` → `uploading` → `validating` → `transcribing` →
`awaiting_input` → `running` → `report_ready` (or `failed`).
"""

DESCRIPTION = (
    "Public API of Onolys (`/v1`, JSON, scoped to the calling user). The contract is this "
    "document; the machine-readable schemas live in `docs/contracts/public/`.\n" + QUICKSTART
)

# statuses every operation can return, plus per-operation ones (kept in step with the routes)
COMMON = (401, 429, 500)
EXTRA: dict[str, tuple[int, ...]] = {
    "createSession": (409, 422),
    "listSessions": (422,),
    "deleteSession": (503,),
    "requestAudioUpload": (409, 422),
    "completeAudioUpload": (409, 503),
    "confirmSpeakers": (409, 422),
    "putRating": (422,),
    "startRun": (409, 422, 429, 503),
}
_REF = {"$ref": "#/components/schemas/ErrorResponse"}


def add_error_responses(schema: dict[str, Any]) -> dict[str, Any]:
    """Point every error status of every operation at `ErrorResponse`; drop the catch-all."""
    from onolys_api.errors import _STATUS_TEXT

    for path, item in schema["paths"].items():
        for op in item.values():
            responses = op["responses"]
            responses.pop("default", None)
            if op["operationId"] == "getHealthz":
                statuses: tuple[int, ...] = (500,)
            else:
                statuses = COMMON + EXTRA.get(op["operationId"], ())
                if "{" in path:
                    statuses += (404,)
            for status in sorted(set(statuses)):
                responses[str(status)] = {
                    "description": _STATUS_TEXT[status],
                    "content": {"application/json": {"schema": _REF}},
                }
            op["responses"] = dict(sorted(responses.items()))
    return schema


_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Onolys API</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{margin:0;font-family:system-ui,sans-serif}</style>
</head>
<body>
<div id="redoc"></div>
<script src="@JS@"></script>
<script>
Redoc.init("/v1/openapi.json", {hideDownloadButton: false, theme: {typography: {
  fontFamily: "system-ui, sans-serif", headings: {fontFamily: "system-ui, sans-serif"},
  code: {fontFamily: "ui-monospace, monospace"}}}}, document.getElementById("redoc"));
</script>
</body>
</html>
""".replace("@JS@", REDOC_JS)


def make_docs_router() -> APIRouter:
    router = APIRouter(prefix="/v1", include_in_schema=False)

    @router.get("/docs")
    def docs() -> HTMLResponse:
        return HTMLResponse(_HTML)

    @router.get("/docs/redoc.standalone.js")
    def redoc_js() -> FileResponse:
        return FileResponse(
            STATIC / "redoc.standalone.js",
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    return router
