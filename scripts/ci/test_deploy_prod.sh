#!/usr/bin/env bash
# Guard for deploy-prod.yml (SP06 Task 13: R13, D5, D6, AC6, AC9). Run from anywhere.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WF="$ROOT/.github/workflows/deploy-prod.yml"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }
has() { grep -Eq -- "$2" "$WF" 2>/dev/null && ok "$1" || bad "$1"; }
hasnt() { grep -Eq -- "$2" "$WF" 2>/dev/null && bad "$1" || ok "$1"; }

[[ -f "$WF" ]] || { bad "deploy-prod.yml exists"; exit 1; }
ok "deploy-prod.yml exists"
has   "manual dispatch trigger"              '^  workflow_dispatch:'
has   "dispatch input sha"                   '^      sha:'
has   "tag v* trigger"                       "- 'v\\*'|- \"v\\*\""
has   "production environment"               "environment: production"
has   "per-env concurrency, no cancel"       'group: deploy-prod'
has   "no cancel-in-progress"                'cancel-in-progress: false'
has   "calls the reusable Cloud Run deploy"  'uses: \./\.github/workflows/_deploy-cloudrun\.yml'
has   "env prod passed to the reusable"      'env: prod'
has   "api service onolys-api-prod"          'service: onolys-api-prod'
has   "worker service onolys-worker-prod"    'service: onolys-worker-prod'
has   "git_sha passed to the revisions"      'git_sha: \$\{\{ needs\.resolve\.outputs\.sha \}\}'
has   "image passed by digest"               'needs\.resolve\.outputs\.image'
has   "matcher copied before the detach checkout" 'cp scripts/ci/staging_ran_image\.py "\$RUNNER_TEMP/staging_ran_image\.py"'
has   "matcher run from RUNNER_TEMP"          'python3 "\$RUNNER_TEMP/staging_ran_image\.py"'
hasnt "matcher not run from the checked-out tree" 'python3 scripts/ci/staging_ran_image\.py'
hasnt "no scratch files in the workspace"    '(-o|>) (index|revisions)\.json'
hasnt "no rebuild (no build-push-action)"    'docker/build-push-action'
has   "resolves tag to digest"               'image_summary\.digest'
has   "checks the digest ran in staging"     'onolys-api-staging'
has   "config guard against the image"       'check_config\.sh --image'
has   "rules to (default) database"          'only .firestore:\(default\).'
hasnt "rules not to staging database"        'firestore:staging'
has   "hosting target app"                   'hosting:app( |$)'
has   "VITE_FIRESTORE_DATABASE (default)"    'VITE_FIRESTORE_DATABASE: "\(default\)"'
has   "prod firebase vars"                   'PROD_VITE_FIREBASE_API_KEY'
has   "uses DEPLOYER_PROD_SA"                'DEPLOYER_PROD_SA'
has   "smoke on app.onolys.com healthz"      'https://app\.onolys\.com/v1/healthz'
has   "smoke checks code_version"            'code_version'
has   "WIF auth"                             'google-github-actions/auth@v2'
hasnt "no JSON key auth"                     'credentials_json|GOOGLE_CREDENTIALS|service_account_key'
hasnt "sha not interpolated in run scripts"  'run:.*\$\{\{ *(inputs|github\.event)\.'

# Version tagging (prod-<date>.<n>) and rollback by version
TAGJOB="$(awk '/^  tag:/{f=1;print;next} f&&/^  [A-Za-z_-]+:/{exit} f{print}' "$WF")"
[[ -n "$TAGJOB" ]] && ok "tag job exists" || bad "tag job exists"
needs_line="$(printf '%s\n' "$TAGJOB" | grep -E '^    needs:' | head -1)"
for j in resolve deploy-api deploy-worker rules web smoke; do
  [[ "$needs_line" =~ (\[|[[:space:],])"$j"([],[:space:]]|$) ]] && ok "tag job needs $j" || bad "tag job needs $j"
done
printf '%s\n' "$TAGJOB" | grep -Eq '^      contents: write' && ok "tag job has contents: write" || bad "tag job has contents: write"
[[ "$(grep -Ec 'contents: write' "$WF")" == 1 ]] && ok "contents: write only on the tag job" || bad "contents: write only on the tag job"
has   "top-level permissions stay read"      '^permissions:'
has   "dispatch input version"               '^      version:'
has   "version regex validation"             'prod-\[0-9\]\{4\}-\[0-9\]\{2\}-\[0-9\]\{2\}\\\.\[0-9\]\+\$'
has   "sha and version mutually exclusive"   'INPUT_SHA.*INPUT_VERSION|INPUT_VERSION.*INPUT_SHA'
has   "version resolved to its commit"       'refs/tags/\$\{INPUT_VERSION\}\^\{commit\}'
has   "next tag via script"                  'scripts/ci/next_prod_tag\.py'
has   "tag pushed"                           'git push origin "refs/tags/'

command -v actionlint >/dev/null 2>&1 && { (cd "$ROOT" && actionlint "$WF") && ok "actionlint" || bad "actionlint"; }
exit $fail
