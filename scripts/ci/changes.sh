#!/usr/bin/env bash
# Per-package CI flags. Reads changed file paths on stdin (one per line).
# Env: FORCE_ALL=true -> every existing package runs (push to main).
#      ROOT=<dir>     -> repo root for directory-exists checks (default: .).
#      GITHUB_OUTPUT  -> where flags are appended (default: stdout).
# A flag is true iff the package exists (python kind: <dir>/pyproject.toml; node kind: <dir>/package.json; else the dir) AND (FORCE_ALL, or its paths or
# shared paths changed). Moving a package = edit its dir in PACKAGES below.
set -euo pipefail

ROOT="${ROOT:-.}"
OUT="${GITHUB_OUTPUT:-/dev/stdout}"

# name:dir:kind (kind python => also triggered by Python-shared paths; node => needs package.json)
PACKAGES=(
  "eaudit:engines/eaudit:python"
  "core:engines/core:python"
  "paudit:engines/paudit:python"
  "evaluation:engines/evaluation:python"
  "api:api:python"
  "frontend:frontend:other"
  "web:web:node"
  "infra:infra:other"
)

# Shared paths: Python-shared hit python packages; CI-shared hits everything.
PY_SHARED_RE='^(pyproject\.toml|uv\.lock|engines/core/)'
CI_SHARED_RE='^(\.github/workflows/|scripts/ci/)'
# Extra paths per package: Firestore rules and their emulator tests run in the api job.
API_EXTRA_RE='^(firestore\.rules|firebase\.json|firestore-rules-test/)'
# The web job also runs on the contracts its generated types come from (gen:api staleness check).
WEB_EXTRA_RE='^(api/openapi\.json|engines/evaluation/schemas/report\.schema\.json)$'

mapfile -t FILES

for entry in "${PACKAGES[@]}"; do
  IFS=: read -r name dir kind <<<"$entry"
  run=false
  marker="$ROOT/$dir"
  [[ "$kind" == python ]] && marker="$ROOT/$dir/pyproject.toml"
  [[ "$kind" == node ]] && marker="$ROOT/$dir/package.json"
  if [[ -e "$marker" ]]; then
    if [[ "${FORCE_ALL:-false}" == "true" ]]; then
      run=true
    else
      for f in "${FILES[@]}"; do
        if [[ "$f" == "$dir/"* || "$f" =~ $CI_SHARED_RE ||
              ( "$kind" == python && "$f" =~ $PY_SHARED_RE ) ||
              ( "$name" == api && "$f" =~ $API_EXTRA_RE ) ||
              ( "$name" == web && "$f" =~ $WEB_EXTRA_RE ) ]]; then
          run=true
          break
        fi
      done
    fi
  fi
  echo "$name=$run" >>"$OUT"
done
