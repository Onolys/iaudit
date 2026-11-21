#!/usr/bin/env bash
# Guard for deploy-admin.yml and scripts/ci/set_admin_origin.sh (SP07 R9). Run from anywhere.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WF="$ROOT/.github/workflows/deploy-admin.yml"
SET="$ROOT/scripts/ci/set_admin_origin.sh"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }
has() { grep -Eq -- "$2" "$WF" 2>/dev/null && ok "$1" || bad "$1"; }
hasnt() { grep -Eq -- "$2" "$WF" 2>/dev/null && bad "$1" || ok "$1"; }

[[ -f "$WF" ]] || { bad "deploy-admin.yml exists"; exit 1; }
ok "deploy-admin.yml exists"
has   "push to main trigger"                 '^  push:'
for p in 'admin/\*\*' 'frontend/\*\*' 'engines/\*\*' 'protocols/\*\*'; do has "push paths include $p" "^      - \"?$p"; done
has   "manual dispatch trigger"              '^  workflow_dispatch:'
hasnt "no prod target (single staging admin env, owner 2026-11-21)" 'prod\)|ADMIN_PROD_|DEPLOYER_PROD_SA|'"'"'production'"'"'|environment: production'
hasnt "no env dispatch input"                'options: \[staging, prod\]'
has   "calls the reusable Cloud Run deploy"  'uses: \./\.github/workflows/_deploy-cloudrun\.yml'
has   "service onolys-admin-backend-staging" 'onolys-admin-backend-staging'
has   "image built from admin/backend/Dockerfile" 'file: admin/backend/Dockerfile'
has   "image passed by digest"               'steps\.push\.outputs\.digest'
has   "git_sha passed to the revision"       'git_sha:'
has   "hosting target admin-staging"         'hosting_target=admin-staging'
has   "VITE_AUTH_REQUIRED true"              'VITE_AUTH_REQUIRED: "true"'
has   "VITE_AUDIT_URL set"                   'VITE_AUDIT_URL:'
has   "origin substituted into firebase.json" 'set_admin_origin\.sh'
has   "anonymous smoke expects 401"          '401'
has   "per-env concurrency, no cancel"       'cancel-in-progress: false'
has   "WIF auth"                             'google-github-actions/auth@v2'
hasnt "no JSON key auth"                     'credentials_json|GOOGLE_CREDENTIALS|service_account_key'
grep -v '^ *#' "$WF" | grep -q 'VITE_EVAL_ENABLED' && bad "does not set VITE_EVAL_ENABLED" || ok "does not set VITE_EVAL_ENABLED"
has   "deploys via hosting:\${HOSTING_TARGET}" 'only "hosting:\$\{HOSTING_TARGET\}"'

# set_admin_origin.sh behaviour
if [[ ! -f "$SET" ]]; then bad "set_admin_origin.sh exists"; exit 1; fi
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
cp "$ROOT/frontend/firebase.json" "$T/fb.json"
bash "$SET" https://admin-x.a.run.app "$T/fb.json" >/dev/null 2>&1 && ok "substitutes a valid origin" || bad "substitutes a valid origin"
grep -q '__ADMIN_BACKEND_ORIGIN__' "$T/fb.json" && bad "no placeholder remains" || ok "no placeholder remains"
[[ "$(grep -c "connect-src 'self' https://admin-x.a.run.app " "$T/fb.json")" == 2 ]] && ok "both targets carry the origin" || bad "both targets carry the origin"
python3 -c "import json,sys; json.load(open('$T/fb.json'))" && ok "result is valid JSON" || bad "result is valid JSON"
cp "$ROOT/frontend/firebase.json" "$T/fb2.json"
for o in "" "http://x.run.app" "https://x.run.app/path" "https://x.run.app;evil" "x.run.app"; do
  bash "$SET" "$o" "$T/fb2.json" >/dev/null 2>&1 && bad "rejects origin '$o'" || ok "rejects origin '$o'"
done
echo '{"no":"placeholder"}' > "$T/fb3.json"
bash "$SET" https://x.run.app "$T/fb3.json" >/dev/null 2>&1 && bad "fails when file has no placeholder" || ok "fails when file has no placeholder"

command -v actionlint >/dev/null 2>&1 && { (cd "$ROOT" && actionlint "$WF") && ok "actionlint" || bad "actionlint"; }
exit $fail
