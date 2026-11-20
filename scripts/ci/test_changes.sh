#!/usr/bin/env bash
# Tests for changes.sh against fake diffs and a fake repo tree.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/engines/eaudit" "$T/frontend" "$T/engines/core" "$T/api" "$T/engines/paudit"
touch "$T/engines/eaudit/pyproject.toml" "$T/engines/core/pyproject.toml" "$T/api/pyproject.toml"
# paudit dir exists but has no pyproject.toml; web/infra/evaluation absent
mkdir -p "$T/web/src"   # web dir without package.json must still skip
fail=0
# run <force> <expected "name=val ..."> <files...>
run() {
  local force="$1" want="$2"; shift 2
  local got
  got="$(printf '%s\n' "$@" | ROOT="$T" FORCE_ALL="$force" GITHUB_OUTPUT=/dev/stdout bash "$HERE/changes.sh" | tr '\n' ' ' | sed 's/ $//')"
  if [[ "$got" == "$want" ]]; then echo "ok   $*"; else echo "FAIL $*"; echo "  got:  $got"; echo "  want: $want"; fail=1; fi
}
run false "eaudit=false core=false paudit=false evaluation=false api=false frontend=true web=false infra=false" frontend/src/a.ts
run false "eaudit=true core=false paudit=false evaluation=false api=false frontend=false web=false infra=false" engines/eaudit/src/x.py
run false "eaudit=true core=true paudit=false evaluation=false api=true frontend=false web=false infra=false" engines/core/x.py
run false "eaudit=true core=true paudit=false evaluation=false api=true frontend=false web=false infra=false" uv.lock
run false "eaudit=true core=true paudit=false evaluation=false api=true frontend=true web=false infra=false" .github/workflows/ci.yml
run false "eaudit=false core=false paudit=false evaluation=false api=false frontend=false web=false infra=false" docs/readme.md
run false "eaudit=false core=false paudit=false evaluation=false api=false frontend=false web=false infra=false" infra/main.tf web/a.ts engines/paudit/a.py
run true  "eaudit=true core=true paudit=false evaluation=false api=true frontend=true web=false infra=false" docs/readme.md
run false "eaudit=false core=false paudit=false evaluation=false api=true frontend=false web=false infra=false" firestore.rules
run false "eaudit=false core=false paudit=false evaluation=false api=true frontend=false web=false infra=false" firestore-rules-test/rules.test.mjs
touch "$T/web/package.json"; mkdir -p "$T/infra"   # web (package.json) and infra (dir) now exist
run false "eaudit=false core=false paudit=false evaluation=false api=false frontend=false web=true infra=false" web/src/a.ts
run false "eaudit=false core=false paudit=false evaluation=false api=false frontend=false web=false infra=true" infra/main.tf
# generated-type inputs (api/openapi.json, report.schema.json) must trigger the web gen:api staleness check
run false "eaudit=false core=false paudit=false evaluation=false api=true frontend=false web=true infra=false" api/openapi.json
run false "eaudit=false core=false paudit=false evaluation=false api=false frontend=false web=true infra=false" engines/evaluation/schemas/report.schema.json
run true  "eaudit=true core=true paudit=false evaluation=false api=true frontend=true web=true infra=true" docs/readme.md
rm "$T/web/package.json" "$T/infra" -r
touch "$T/engines/paudit/pyproject.toml"   # now paudit exists
run false "eaudit=false core=false paudit=true evaluation=false api=false frontend=false web=false infra=false" engines/paudit/a.py
exit $fail
