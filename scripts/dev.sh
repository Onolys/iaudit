#!/usr/bin/env bash
# Start backend (8000), eval server (8100) and Vite (5173) together.
# Usage: scripts/dev.sh [--check] [--stub]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT=8000
EVAL_PORT=8100
WEB_PORT=5173
CHECK_ONLY=0
STUB=0

for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --stub) STUB=1 ;;
    -h|--help) sed -n '2,3p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown flag: $arg (use --check, --stub)" >&2; exit 2 ;;
  esac
done

port_holder() {
  # Prints a description of the process listening on $1, or nothing if free.
  local port=$1 out=""
  if command -v ss >/dev/null 2>&1; then
    out="$(ss -ltnpH "sport = :$port" 2>/dev/null | head -n1 || true)"
    if [ -n "$out" ]; then
      local users
      users="$(printf '%s' "$out" | grep -o 'users:.*' || true)"
      echo "${users:-listening (holder unknown)}"
      return 0
    fi
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    out="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sed -n '2p' || true)"
    [ -n "$out" ] && echo "$out"
    return 0
  fi
  return 0
}

preflight() {
  local failed=0
  command -v uv >/dev/null 2>&1 || { echo "preflight: 'uv' not found on PATH" >&2; failed=1; }
  command -v node >/dev/null 2>&1 || { echo "preflight: 'node' not found on PATH" >&2; failed=1; }
  command -v npm >/dev/null 2>&1 || { echo "preflight: 'npm' not found on PATH" >&2; failed=1; }
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    echo "preflight: frontend/node_modules missing. Run: (cd frontend && npm ci)" >&2
    failed=1
  fi
  local p holder
  for p in "$BACKEND_PORT" "$EVAL_PORT" "$WEB_PORT"; do
    holder="$(port_holder "$p")"
    if [ -n "$holder" ]; then
      echo "preflight: port $p is in use by: $holder" >&2
      failed=1
    fi
  done
  local have_key=0 k
  for k in ANTHROPIC_API_KEY OPENAI_API_KEY LITELLM_API_KEY; do
    [ -n "${!k:-}" ] && have_key=1
  done
  if [ "$have_key" -eq 0 ] && [ "$STUB" -eq 0 ]; then
    echo "warning: none of ANTHROPIC_API_KEY / OPENAI_API_KEY / LITELLM_API_KEY is set; live runs will fail (use --stub for the stub pipeline)" >&2
  fi
  return "$failed"
}

if ! preflight; then
  echo "preflight failed" >&2
  exit 1
fi
if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "preflight ok"
  exit 0
fi

PIDS=()
CLEANED=0

launch() {
  # launch <label> <dir> <cmd...>: own session/process group, prefixed output.
  local label=$1 dir=$2
  shift 2
  if command -v setsid >/dev/null 2>&1; then
    ( cd "$ROOT/$dir" && exec setsid "$@" ) > >(sed -u "s/^/[$label] /") 2>&1 &
  else
    ( cd "$ROOT/$dir" && exec "$@" ) > >(sed -u "s/^/[$label] /") 2>&1 &
  fi
  PIDS+=("$!")
}

signal_all() {
  local sig=$1 pid
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] || continue
    kill "-$sig" -- "-$pid" 2>/dev/null || kill "-$sig" "$pid" 2>/dev/null || true
  done
}

cleanup() {
  local code=$?
  trap - INT TERM EXIT
  if [ "$CLEANED" -eq 0 ]; then
    CLEANED=1
    if [ "${#PIDS[@]}" -gt 0 ]; then
      signal_all TERM
      local i alive pid
      for i in 1 2 3 4 5 6 7 8 9 10; do
        alive=0
        for pid in "${PIDS[@]}"; do
          kill -0 "$pid" 2>/dev/null && alive=1
        done
        [ "$alive" -eq 0 ] && break
        sleep 0.5
      done
      [ "$alive" -eq 1 ] && signal_all KILL
      wait 2>/dev/null || true
    fi
  fi
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "$STUB" -eq 1 ]; then export IAUDIT_PIPELINE=stub; fi

launch backend backend uv run uvicorn iaudit_backend.app:app --port "$BACKEND_PORT"
launch eval eval env "IAUDIT_BACKEND_URL=http://127.0.0.1:$BACKEND_PORT" \
  uv run uvicorn iaudit_eval.server.app:app --host 127.0.0.1 --port "$EVAL_PORT"
launch web frontend env "VITE_AUDIT_URL=http://localhost:$BACKEND_PORT/v1/audit" \
  VITE_MOCK=false "IAUDIT_EVAL_PORT=$EVAL_PORT" npm run dev

any_dead() {
  local pid
  for pid in "${PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null || return 0
  done
  return 1
}

healthy() { # healthy <url>
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null --max-time 2 "$1" 2>/dev/null
  else
    python3 -c "import urllib.request,sys; urllib.request.urlopen(sys.argv[1], timeout=2)" "$1" 2>/dev/null
  fi
}

backend_ok=0
eval_ok=0
for _ in $(seq 1 30); do
  if any_dead; then
    echo "a child process exited during startup; stopping" >&2
    exit 1
  fi
  [ "$backend_ok" -eq 1 ] || { healthy "http://127.0.0.1:$BACKEND_PORT/healthz" && backend_ok=1 || true; }
  [ "$eval_ok" -eq 1 ] || { healthy "http://127.0.0.1:$EVAL_PORT/health" && eval_ok=1 || true; }
  [ "$backend_ok" -eq 1 ] && [ "$eval_ok" -eq 1 ] && break
  sleep 1
done
if [ "$backend_ok" -ne 1 ] || [ "$eval_ok" -ne 1 ]; then
  echo "health wait timed out after 30s (backend ok=$backend_ok, eval ok=$eval_ok)" >&2
  exit 1
fi

echo "Ready:"
echo "  backend  http://127.0.0.1:$BACKEND_PORT/healthz"
echo "  eval api http://127.0.0.1:$EVAL_PORT/health"
echo "  web      http://localhost:$WEB_PORT"
echo "Ctrl-C to stop all."

while ! any_dead; do
  sleep 1
done
echo "a child process exited; stopping the rest" >&2
exit 1
