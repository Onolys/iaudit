#!/usr/bin/env bash
# Guard (SP06 R14): config/{staging,prod}/{routes,stt_providers}.yaml must exist and be non-empty.
#   check_config.sh                  # check the source tree (ROOT, default: repo root)
#   check_config.sh --image <ref>    # also check inside a built image (/app/config/...)
# Image mode runs `docker run --rm --entrypoint test <ref> -s /app/config/<env>/<file>`.
set -uo pipefail
ROOT="${ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
image=""
if [[ "${1:-}" == "--image" ]]; then image="${2:?--image needs an image reference}"; fi
rc=0
for env in staging prod; do
  for f in routes stt_providers; do
    rel="config/$env/$f.yaml"
    if [[ ! -s "$ROOT/$rel" ]]; then echo "MISSING or empty in repo: $rel" >&2; rc=1; fi
    if [[ -n "$image" ]] && ! docker run --rm --entrypoint test "$image" -s "/app/$rel"; then
      echo "MISSING or empty in image $image: /app/$rel" >&2; rc=1
    fi
  done
done
[[ $rc -eq 0 ]] && echo "config guard: ok"
exit $rc
