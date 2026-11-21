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
has   "voice service onolys-voice-prod"      'service: onolys-voice-prod'
has   "voice runs with SERVICE_MODE=voice"   'SERVICE_MODE=voice'
has   "digest check covers the staging voice service" 'onolys-worker-staging onolys-voice-staging'
has   "git_sha passed to the revisions"      'git_sha: \$\{\{ needs\.resolve\.outputs\.sha \}\}'
has   "image passed by digest"               'needs\.resolve\.outputs\.image'
has   "matcher copied before the detach checkout" 'cp scripts/ci/staging_ran_image\.py "\$RUNNER_TEMP/staging_ran_image\.py"'
has   "matcher run from RUNNER_TEMP, isolated (python3 -I)" 'python3 -I "\$RUNNER_TEMP/staging_ran_image\.py"'
hasnt "matcher never run without -I"         'python3 "\$RUNNER_TEMP/staging_ran_image'
has   "config guard copied before the detach checkout" 'cp scripts/ci/check_config\.sh "\$RUNNER_TEMP/check_config\.sh"'
cpl="$(grep -n 'cp scripts/ci/check_config.sh' "$WF" | head -1 | cut -d: -f1)"; col="$(grep -n 'git checkout --detach' "$WF" | head -1 | cut -d: -f1)"
[[ -n "$cpl" && -n "$col" && "$cpl" -lt "$col" ]] && ok "config guard copy precedes git checkout --detach" || bad "config guard copy precedes git checkout --detach"
has   "config guard runs the RUNNER_TEMP copy in an empty env on the target tree" 'env -i .*ROOT="\$GITHUB_WORKSPACE" bash "\$RUNNER_TEMP/check_config\.sh"$'
hasnt "no target-tree check_config.sh is ever run (both guards use the RUNNER_TEMP copy)" 'bash scripts/ci/check_config\.sh'
has   "image guard runs the RUNNER_TEMP copy in an empty env" 'env -i .*bash "\$RUNNER_TEMP/check_config\.sh" --image "\$IMAGE"'
hasnt "matcher not run from the checked-out tree" 'python3 scripts/ci/staging_ran_image\.py'
hasnt "no scratch files in the workspace"    '(-o|>) (index|revisions)\.json'
hasnt "no rebuild (no build-push-action)"    'docker/build-push-action'
has   "resolves tag to digest"               'image_summary\.digest'
has   "checks the digest ran in staging"     'onolys-api-staging'
has   "config guard against the image"       'check_config\.sh" --image'
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
for j in resolve deploy-api deploy-worker deploy-voice rules web smoke; do
  [[ "$needs_line" =~ (\[|[[:space:],])"$j"([],[:space:]]|$) ]] && ok "tag job needs $j" || bad "tag job needs $j"
done
printf '%s\n' "$TAGJOB" | grep -Eq '^      contents: write' && ok "tag job has contents: write" || bad "tag job has contents: write"
[[ "$(grep -Ec 'contents: write' "$WF")" == 1 ]] && ok "contents: write only on the tag job" || bad "contents: write only on the tag job"
has   "top-level permissions stay read"      '^permissions:'
has   "dispatch input version"               '^      version:'
has   "version regex validation"             'prod-\[0-9\]\{4\}-\[0-9\]\{2\}-\[0-9\]\{2\}\\\.\[0-9\]\+\$'
has   "sha and version mutually exclusive"   'INPUT_SHA.*INPUT_VERSION|INPUT_VERSION.*INPUT_SHA'
has   "version resolved to its commit"       'refs/tags/\$\{INPUT_VERSION\}\^\{commit\}'
hasnt "no python script for tag naming"      'next_prod_tag'
printf '%s\n' "$TAGJOB" | grep -Eq 'set -o pipefail|set -[a-z]*o pipefail|shell: bash' && ok "tag step has pipefail" || bad "tag step has pipefail"
printf '%s\n' "$TAGJOB" | grep -Eq 'git ls-remote --tags --refs origin "prod-\$d\.\*"' && ok "tag N computed inline from ls-remote" || bad "tag N computed inline from ls-remote"
has   "resolve summary shows sha"            'GITHUB_STEP_SUMMARY'
# Run the real n=/tag= snippet from the workflow against fixture ls-remote output (.9/.10 ordering, none -> .1, other days ignored)
snippet="$(printf '%s\n' "$TAGJOB" | grep -E '^ *(n=|tag=)' | sed 's/^ *//')"
check_tag() { # $1 = expected, $2 = fixture lines
  got="$(FIXTURE="$2" bash -c 'set -o pipefail; git() { printf "%b" "$FIXTURE"; }; d=2026-11-21; '"$snippet"'; echo "$tag"' 2>&1)"
  [[ "$got" == "$1" ]] && ok "tag snippet: $1" || { bad "tag snippet: expected $1 got '$got'"; }
}
check_tag "prod-2026-11-21.1"  ""
check_tag "prod-2026-11-21.11" "aaa\trefs/tags/prod-2026-11-21.9\nbbb\trefs/tags/prod-2026-11-21.10\nccc\trefs/tags/prod-2026-11-21.2\n"
check_tag "prod-2026-11-21.4"  "aaa\trefs/tags/prod-2026-11-21.3\nbbb\trefs/tags/prod-2026-11-20.99\n"
has   "tag pushed"                           'git push origin "refs/tags/'
# Old-commit tag push: a shallow checkout makes git upload the commit's trees/blobs (incl. .github/workflows), which GITHUB_TOKEN may not push
printf '%s\n' "$TAGJOB" | grep -Eq 'fetch-depth: 0' && ok "tag job checks out full history" || bad "tag job checks out full history"
printf '%s\n' "$TAGJOB" | grep -Eq 'git fetch .*--depth' && bad "tag job must not shallow-fetch the target sha" || ok "tag job does not shallow-fetch the target sha"

# Behaviour of the config guard as the workflow runs it: workflow-ref copy, empty env, target tree passed as ROOT (data only)
GT="$(mktemp -d)"; trap 'rm -rf "$GT"' EXIT
cp "$ROOT/scripts/ci/check_config.sh" "$GT/check_config.sh"
env -i PATH=/usr/bin:/bin HOME="$GT" ROOT="$ROOT" bash "$GT/check_config.sh" >/dev/null 2>&1 && ok "config guard (copy, env -i) passes on a valid target tree" || bad "config guard (copy, env -i) passes on a valid target tree"
mkdir -p "$GT/empty"
env -i PATH=/usr/bin:/bin HOME="$GT" ROOT="$GT/empty" bash "$GT/check_config.sh" >/dev/null 2>&1 && bad "config guard still rejects a target tree missing config" || ok "config guard still rejects a target tree missing config"
# a hostile target tree cannot influence the guard: its own scripts/ci/check_config.sh (would pass) is never run
mkdir -p "$GT/evil/scripts/ci"; printf '#!/usr/bin/env bash\ntouch "%s/pwned"; echo "config guard: ok"\n' "$GT" > "$GT/evil/scripts/ci/check_config.sh"
env -i PATH=/usr/bin:/bin HOME="$GT" ROOT="$GT/evil" bash "$GT/check_config.sh" >/dev/null 2>&1 && bad "guard ignores the target's own check_config.sh" || ok "guard ignores the target's own check_config.sh"
[[ ! -e "$GT/pwned" ]] && ok "target-tree script never executed" || bad "target-tree script never executed"

command -v actionlint >/dev/null 2>&1 && { (cd "$ROOT" && actionlint "$WF") && ok "actionlint" || bad "actionlint"; }
exit $fail
