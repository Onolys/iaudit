#!/bin/sh
# One image, three roles (PRD D6). SERVICE_MODE = api | worker | combined (default api).
# Cloud Run injects PORT; the app reads every other setting from the environment (api/.env.example).
set -eu
case "${SERVICE_MODE:-api}" in
  api|worker|combined) ;;
  *) echo "SERVICE_MODE must be api, worker or combined (got '${SERVICE_MODE}')" >&2; exit 2 ;;
esac
export SERVICE_MODE="${SERVICE_MODE:-api}"
exec uvicorn --factory onolys_api.app:create_app \
  --host 0.0.0.0 --port "${PORT:-8080}" --no-access-log --proxy-headers --forwarded-allow-ips='*'
