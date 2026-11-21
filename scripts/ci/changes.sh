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
  "admin-auth:admin/auth:python"
  "admin-backend:admin/backend:python"
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

# paudit packs are built from protocols/ (and the admin image ships it, see ADMIN_BACKEND_EXTRA_RE).
PAUDIT_EXTRA_RE='^protocols/'

# The frontend's pauditSchema.test.ts imports the paudit result schema through the @paudit-schema alias.
FRONTEND_EXTRA_RE='^engines/paudit/schemas/'

# The admin gateway mounts eaudit, uses admin/auth and paudit, and its image ships protocols/ and
# docs/contracts/, so it re-runs when any of them (or .dockerignore) changes.
ADMIN_BACKEND_EXTRA_RE='^(admin/auth/|engines/eaudit/|engines/paudit/|protocols/|docs/contracts/|\.dockerignore)'

# Direct workspace dependencies (name: deps), mirrored from each pyproject [project].dependencies.
# A change in a package also runs every package that (transitively) depends on it.
# test_changes_deps.py fails if this drifts from the pyprojects.
DEPS=(
  "eaudit:core"
  "paudit:core"
  "evaluation:core eaudit paudit"
  "api:core evaluation paudit"
  "admin-backend:admin-auth eaudit core paudit"
)

mapfile -t FILES

declare -A HIT=()
for entry in "${PACKAGES[@]}"; do
  IFS=: read -r name dir kind <<<"$entry"
  for f in "${FILES[@]}"; do
    if [[ "$f" == "$dir/"* || "$f" =~ $CI_SHARED_RE ||
          ( "$kind" == python && "$f" =~ $PY_SHARED_RE ) ||
          ( "$name" == api && "$f" =~ $API_EXTRA_RE ) ||
          ( "$name" == paudit && "$f" =~ $PAUDIT_EXTRA_RE ) ||
          ( "$name" == admin-backend && "$f" =~ $ADMIN_BACKEND_EXTRA_RE ) ||
          ( "$name" == frontend && "$f" =~ $FRONTEND_EXTRA_RE ) ||
          ( "$name" == web && "$f" =~ $WEB_EXTRA_RE ) ]]; then
      HIT[$name]=1
      break
    fi
  done
done

# Propagate to dependents until stable.
changed=true
while [[ "$changed" == true ]]; do
  changed=false
  for entry in "${DEPS[@]}"; do
    name="${entry%%:*}"
    [[ -n "${HIT[$name]:-}" ]] && continue
    for dep in ${entry#*:}; do
      if [[ -n "${HIT[$dep]:-}" ]]; then HIT[$name]=1; changed=true; break; fi
    done
  done
done

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
      [[ -n "${HIT[$name]:-}" ]] && run=true
    fi
  fi
  echo "$name=$run" >>"$OUT"
done
