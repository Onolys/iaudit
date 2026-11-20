#!/usr/bin/env bash
# Run the API locally in SERVICE_MODE=combined (api + worker in one process) with fakes:
# fake auth, in-memory Firestore/queue, local-dir blob store, stub STT/evaluation. No GCP, no network.
# Usage: api/scripts/dev.sh [--check] [--quickstart]
#   (none)        serve on $PORT (default 8000) until Ctrl-C
#   --quickstart  start, run the quickstart curl script from the OpenAPI description, stop
#   --check       preflight only (tools and free port), then exit
# Try it:  curl -H 'Authorization: Bearer test:alice' localhost:8000/v1/sessions
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${PORT:-8000}"
MODE=serve

for arg in "$@"; do
  case "$arg" in
    --check) MODE=check ;;
    --quickstart) MODE=quickstart ;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown flag: $arg (use --check, --quickstart)" >&2; exit 2 ;;
  esac
done

need=(uv)
[ "$MODE" = quickstart ] && need+=(curl jq ffmpeg)
failed=0
for tool in "${need[@]}"; do
  command -v "$tool" >/dev/null 2>&1 || { echo "preflight: '$tool' not found on PATH" >&2; failed=1; }
done
if command -v ss >/dev/null 2>&1 && [ -n "$(ss -ltnH "sport = :$PORT" 2>/dev/null)" ]; then
  echo "preflight: port $PORT is in use (set PORT=<free port>)" >&2
  failed=1
fi
[ "$failed" = 0 ] || exit 1
[ "$MODE" = check ] && { echo "preflight ok (port $PORT)"; exit 0; }

WORK="$(mktemp -d)"
SERVER_PID=""
cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null && wait "$SERVER_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

export ENV=local SERVICE_MODE=combined AUTH_MODE=fake ADAPTERS=stub GIT_SHA="${GIT_SHA:-dev}"
export FAKE_BLOB_DIR="$WORK/blobs" FAKE_BLOB_BASE_URL="http://127.0.0.1:$PORT"
unset FIRESTORE_EMULATOR_HOST

cd "$ROOT"
UVICORN=(uv run --package onolys-api uvicorn --factory onolys_api.app:create_app
  --host 127.0.0.1 --port "$PORT")

if [ "$MODE" = serve ]; then
  echo "onolys-api combined mode on http://127.0.0.1:$PORT/v1 (docs: /v1/docs)"
  echo "auth: -H 'Authorization: Bearer test:<any uid>'"
  "${UVICORN[@]}"
  exit 0
fi

"${UVICORN[@]}" >"$WORK/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 100); do
  curl -sf "http://127.0.0.1:$PORT/v1/healthz" >/dev/null 2>&1 && break
  kill -0 "$SERVER_PID" 2>/dev/null || { cat "$WORK/server.log" >&2; echo "server exited" >&2; exit 1; }
  sleep 0.3
done
curl -sf "http://127.0.0.1:$PORT/v1/healthz" >/dev/null || { cat "$WORK/server.log" >&2; exit 1; }

ffmpeg -nostdin -v error -f lavfi -i "sine=frequency=440:duration=2" -c:a aac "$WORK/session.m4a"
curl -sf "http://127.0.0.1:$PORT/v1/openapi.json" | jq -r .info.description \
  | awk '/^```bash$/{f=1;next} /^```$/{f=0} f' >"$WORK/quickstart.sh"
[ -s "$WORK/quickstart.sh" ] || { echo "no quickstart in the OpenAPI description" >&2; exit 1; }

BASE="http://127.0.0.1:$PORT/v1" AUTH="Authorization: Bearer test:dev" AUDIO="$WORK/session.m4a" \
  bash "$WORK/quickstart.sh"
