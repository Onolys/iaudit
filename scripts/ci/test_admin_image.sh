#!/usr/bin/env bash
# Smoke test for admin/backend/Dockerfile (SP07 R9). Run from anywhere; builds from the repo root.
#   bash scripts/ci/test_admin_image.sh [image-tag]     (SKIP_BUILD=1 to reuse an existing image)
# Checks: (1) auth on + test allowlist -> anonymous /healthz and /v1/paudit/fixtures give 401;
# (2) empty allowlist exits non-zero; (3) image listing has no eval/datasets/transcript data.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMG="${1:-onolys-admin-backend:ci}"
NAME="onolys-admin-smoke-$$"
PORT="${SMOKE_PORT:-18080}"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || { echo "FAIL docker not found"; exit 1; }

if [[ -z "${SKIP_BUILD:-}" ]]; then
  [[ -f "$ROOT/admin/backend/Dockerfile" ]] || { echo "FAIL admin/backend/Dockerfile missing"; exit 1; }
  docker build -f "$ROOT/admin/backend/Dockerfile" -t "$IMG" "$ROOT" >/dev/null || { echo "FAIL build"; exit 1; }
  ok "image builds"
fi

# 1. auth on (image default) + allowlist: anonymous calls are rejected with 401.
docker run -d --name "$NAME" -p "$PORT:8080" -e ADMIN_ALLOWED_EMAILS=test@example.com \
  -e ADMIN_AUTH_PROJECT=demo-project "$IMG" >/dev/null
code=000
for _ in $(seq 1 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "localhost:$PORT/healthz" || true)"
  [[ "$code" != 000 ]] && break
  sleep 1
done
[[ "$code" == 401 ]] && ok "anonymous /healthz -> 401" || { bad "anonymous /healthz -> $code (want 401)"; docker logs "$NAME" 2>&1 | tail -20; }
code="$(curl -s -o /dev/null -w '%{http_code}' "localhost:$PORT/v1/paudit/fixtures" || true)"
[[ "$code" == 401 ]] && ok "anonymous /v1/paudit/fixtures -> 401" || bad "anonymous /v1/paudit/fixtures -> $code (want 401)"
cleanup

# 2. empty allowlist: refuses to start.
timeout 60 docker run --rm -e ADMIN_ALLOWED_EMAILS= -e ADMIN_AUTH_PROJECT=demo-project "$IMG" >/dev/null 2>&1
rc=$?
[[ $rc -ne 0 && $rc -ne 124 ]] && ok "empty allowlist exits non-zero (rc=$rc)" || bad "empty allowlist rc=$rc (want non-zero, not timeout)"

# 3. listing: no eval code/datasets/transcript data; synthetic pack fixtures are expected.
found="$(docker run --rm --entrypoint sh "$IMG" -c \
  'find / -xdev \( -name datasets -o -name eval -o -name evaluation -o -name "onolys_evaluation*" -o -name "*.jsonl" -o -name "*.vtt" -o -name "*.srt" \) -not -path "/proc/*" -not -path "/protocols/*" -not -path "/app/protocols/*" 2>/dev/null')"
[[ -z "$found" ]] && ok "no eval/datasets/transcript paths in image" || { bad "unexpected paths in image:"; echo "$found"; }
docker run --rm --entrypoint test "$IMG" -f /app/protocols/miti-4.2.1/pack.yaml && ok "protocols pack present" || bad "protocols pack missing"

exit $fail
