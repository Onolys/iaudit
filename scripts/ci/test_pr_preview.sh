#!/usr/bin/env bash
# Guard for pr-preview.yml, pr-preview-cleanup.yml and scripts/ci/pr_preview.sh (SP00 R3). Run from anywhere.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WF="$ROOT/.github/workflows/pr-preview.yml"
DS="$ROOT/.github/workflows/deploy-staging.yml"
DC="$ROOT/.github/workflows/_deploy-cloudrun.yml"
CL="$ROOT/.github/workflows/pr-preview-cleanup.yml"
PP="$ROOT/scripts/ci/pr_preview.sh"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }
has()   { grep -Eq -- "$3" "$2" 2>/dev/null && ok "$1" || bad "$1"; }
hasnt() { grep -Eq -- "$3" "$2" 2>/dev/null && bad "$1" || ok "$1"; }

for f in "$WF" "$CL" "$PP"; do [[ -f "$f" ]] && ok "exists: ${f#"$ROOT"/}" || { bad "exists: ${f#"$ROOT"/}"; }; done
[[ -f "$WF" && -f "$CL" && -f "$PP" ]] || exit 1

# --- pr-preview.yml
has   "triggers: opened, synchronize, reopened" "$WF" 'types: \[opened, synchronize, reopened\]'
has   "same-repo guard"                         "$WF" 'github\.event\.pull_request\.head\.repo\.full_name == github\.repository'
has   "concurrency per PR number"               "$WF" 'group: pr-preview-\$\{\{ github\.event\.number \}\}'
has   "cancel-in-progress true"                 "$WF" 'cancel-in-progress: true'
has   "WIF auth"                                "$WF" 'google-github-actions/auth@v2'
has   "deployer-staging SA var"                 "$WF" 'vars\.DEPLOYER_STAGING_SA'
hasnt "no JSON key auth"                        "$WF" 'credentials_json|GOOGLE_CREDENTIALS|service_account_key'
has   "image tag pr-<N>-<sha>"                  "$WF" 'pr-\$\{\{ github\.event\.number \}\}-'
has   "preview = tagged revision on the staging API service" "$WF" 'service=onolys-api-staging'
hasnt "no separate onolys-pr-<N> service"       "$WF" 'onolys-pr-[$"{0-9]'
has   "no-traffic deploy"                       "$WF" '--no-traffic'
has   "tag pr-<N>"                              "$WF" '--tag "pr-\$\{PR\}"'
has   "deterministic revision suffix"           "$WF" '--revision-suffix "\$SUFFIX"'
has   "suffix has pr, sha, run number, attempt" "$WF" 'revision_suffix=pr-\$\{PR\}-\$\{SHA:0:7\}-\$\{GITHUB_RUN_NUMBER\}-\$\{GITHUB_RUN_ATTEMPT\}'
hasnt "no traffic flags that could route to the preview" "$WF" '--to-latest|--to-revisions|--set-tags|update-traffic'
hasnt "no IAM change from the preview"          "$WF" '--allow-unauthenticated|add-iam-policy-binding'
hasnt "no service-level label leak"             "$WF" '--labels'
has   "combined mode via env-overrides helper"  "$WF" 'pr_preview\.sh env-overrides'
has   "fake adapters by default (adapters=stub)" "$WF" 'adapters=stub; mode=fake'
hasnt "no inline --set-env-vars"                "$WF" '--set-env-vars'
hasnt "no --env-vars-file (it would wipe the staging service env)" "$WF" '--env-vars-file'
has   "env merged via --update-env-vars"        "$WF" '--update-env-vars'
hasnt "no instance-limit flags (staging service scaling untouched)" "$WF" '--max-instances|--min-instances'
has   "CPU always allocated"                    "$WF" '--no-cpu-throttling'
has   "tag URL resolved from the service URL"   "$WF" 'pr_preview\.sh tag-url'
has   "web calls the tag URL"                   "$WF" 'VITE_API_BASE_URL: \$\{\{ steps\.api\.outputs\.url \}\}/v1'
has   "preflight smoke for the channel origin"  "$WF" 'Access-Control-Request-Method'
hasnt "no shared concurrency group with deploy-staging (documented why)" "$WF" 'group: deploy-staging|group: cloudrun'
has   "web built with staging settings"         "$WF" 'VITE_FIRESTORE_DATABASE: staging'
has   "staging firebase vars"                   "$WF" 'STAGING_VITE_FIREBASE_API_KEY'
has   "generates firebase config via helper"    "$WF" 'pr_preview\.sh firebase-config'
has   "channel pr-<N>, 7d expiry"               "$WF" '--expires 7d'
has   "firebase-tools pinned 15\.37\.0"          "$WF" 'FIREBASE_TOOLS_VERSION: 15\.37\.0'
has   "marker comment via helper"               "$WF" 'pr_preview\.sh comment'
has   "pull-requests: write"                    "$WF" 'pull-requests: write'
has   "preview-real label wired"                "$WF" 'preview-real'
hasnt "no LLM/STT secret names"                 "$WF" '(ANTHROPIC|GEMINI|OPENAI|DEEPGRAM|ASSEMBLYAI|STT|LLM)_[A-Z0-9_]*(KEY|TOKEN|SECRET)'
hasnt "no pull_request_target"                  "$WF" 'pull_request_target'
(cd "$ROOT" && python3 scripts/ci/check_no_llm_keys_in_pr_workflows.py >/dev/null) && ok "key guard passes" || bad "key guard passes"

# --- deploy-staging.yml / _deploy-cloudrun.yml: previews share the staging API service, so staging must not inherit them
has   "staging api resets SERVICE_MODE=api"     "$DS" 'SERVICE_MODE=api'
has   "staging api resets ADAPTERS=real"        "$DS" 'ADAPTERS=real'
has   "staging api resets CORS_ORIGINS"         "$DS" 'CORS_ORIGINS=https://onolys-app-staging\.web\.app'
has   "staging api resets CPU throttling"       "$DS" 'flags: --cpu-throttling'
has   "staging api pins traffic to its revision" "$DS" 'pin_traffic: true'
has   "reusable: named revision + 100% traffic" "$DC" 'revision_traffic: \$\{\{ steps\.rev\.outputs\.traffic \}\}'
has   "reusable: unique revision suffix"        "$DC" 'GITHUB_RUN_NUMBER\}-\$\{GITHUB_RUN_ATTEMPT'
# every key the preview overrides is reset by staging
ov="$(bash "$PP" env-overrides stub abcdef1234567890 https://x.web.app | tr '|' '\n' | sed '1d' | cut -d= -f1 | tr -d '^')"
for k in $ov; do
  case "$k" in GIT_SHA) continue ;; esac
  grep -q "$k=" "$DS" && ok "staging re-specifies preview-overridden $k" || bad "staging re-specifies preview-overridden $k"
done

# --- pr-preview-cleanup.yml
has   "cleanup on pull_request closed"          "$CL" 'types: \[closed\]'
has   "cleanup same-repo guard"                 "$CL" 'github\.event\.pull_request\.head\.repo\.full_name == github\.repository'
has   "cleanup WIF auth"                        "$CL" 'google-github-actions/auth@v2'
has   "cleanup deployer-staging SA var"         "$CL" 'vars\.DEPLOYER_STAGING_SA'
has   "cleanup concurrency shares preview group" "$CL" 'group: pr-preview-\$\{\{ github\.event\.number \}\}'
has   "cleanup removes the tag and revisions via helper"                     "$CL" 'pr_preview\.sh cleanup'
hasnt "cleanup no JSON key auth"                "$CL" 'credentials_json|GOOGLE_CREDENTIALS|service_account_key'

# --- helper: firebase-config
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
API=https://pr-42---onolys-api-staging-abc123-uc.a.run.app
bash "$PP" firebase-config "$API" "$ROOT/web/firebase.json" "$T/fb.json" >/dev/null 2>&1 && ok "firebase-config runs" || bad "firebase-config runs"
python3 - "$T/fb.json" "$API" <<'PY' && ok "config: target app-staging only, no Cloud Run rewrite, SPA fallback kept, tag origin in CSP connect-src" || bad "config: target app-staging only, no Cloud Run rewrite, SPA fallback kept, tag origin in CSP connect-src"
import json, sys
c = json.load(open(sys.argv[1])); api = sys.argv[2]
h = c["hosting"]
assert len(h) == 1 and h[0]["target"] == "app-staging", h
r = h[0]["rewrites"]
assert r == [{"source": "**", "destination": "/index.html"}], r
assert h[0]["public"] == "dist"
csp = [x["value"] for g in h[0]["headers"] for x in g["headers"] if x["key"] == "Content-Security-Policy"]
assert len(csp) == 1 and f"connect-src {api} 'self'" in csp[0] and csp[0].count(api) == 1, csp
PY
grep -q 'onolys-api-prod\|"serviceId"' "$T/fb.json" && bad "no Cloud Run service left in config" || ok "no Cloud Run service left in config"
for a in "" "http://x.run.app" "https://x.run.app/v1" "https://x;evil"; do
  bash "$PP" firebase-config "$a" "$ROOT/web/firebase.json" "$T/x.json" >/dev/null 2>&1 && bad "rejects api origin '$a'" || ok "rejects api origin '$a'"
done
echo '{"hosting":[{"target":"other","rewrites":[]}]}' > "$T/nofb.json"
bash "$PP" firebase-config "$API" "$T/nofb.json" "$T/x.json" >/dev/null 2>&1 && bad "fails without app-staging target" || ok "fails without app-staging target"
echo '{"hosting":[{"target":"app-staging","rewrites":[{"source":"/v1/**","run":{"serviceId":"s"}}]}]}' > "$T/norw.json"
bash "$PP" firebase-config "$API" "$T/norw.json" "$T/x.json" >/dev/null 2>&1 && bad "fails without SPA fallback" || ok "fails without SPA fallback"

# --- helper: env-overrides (gcloud --update-env-vars with ^|^ delimiter) and tag-url
ovr="$(bash "$PP" env-overrides stub abcdef1234567890abcdef1234567890abcdef12 https://onolys-app-staging--pr-42-x1.web.app)"
[[ "$ovr" == "^|^SERVICE_MODE=combined|ADAPTERS=stub|GIT_SHA=abcdef1234567890abcdef1234567890abcdef12|CORS_ORIGINS=https://onolys-app-staging--pr-42-x1.web.app" ]] && ok "env-overrides: combined, stub, sha, CORS = channel origin only" || bad "env-overrides output: $ovr"
bash "$PP" env-overrides stub "bad sha" https://x.web.app >/dev/null 2>&1 && bad "env-overrides rejects bad sha" || ok "env-overrides rejects bad sha"
bash "$PP" env-overrides stub abcdef1 "https://x.web.app|EVIL=1" >/dev/null 2>&1 && bad "env-overrides rejects delimiter injection" || ok "env-overrides rejects delimiter injection"
[[ "$(bash "$PP" tag-url https://onolys-api-staging-abc123-uc.a.run.app 42)" == "https://pr-42---onolys-api-staging-abc123-uc.a.run.app" ]] && ok "tag-url form" || bad "tag-url form"
[[ "$(bash "$PP" tag-url https://onolys-api-staging-abc123-uc.a.run.app/ 7)" == "https://pr-7---onolys-api-staging-abc123-uc.a.run.app" ]] && ok "tag-url strips trailing slash" || bad "tag-url strips trailing slash"
bash "$PP" tag-url http://x.run.app 7 >/dev/null 2>&1 && bad "tag-url rejects http" || ok "tag-url rejects http"
# channel-url: firebase-tools keys .result by hosting TARGET, not site (real output, run 44844044832)
cat > "$T/channel.json" <<'JSON'
{"status":"success","result":{"app-staging":{"target":"app-staging","site":"onolys-app-staging","url":"https://onolys-app-staging--pr-35-kkj34ogl.web.app","version":"4e325a6713286451","expireTime":"2026-11-28T00:00:00.000Z"}}}
JSON
[[ "$(bash "$PP" channel-url "$T/channel.json" onolys-app-staging)" == "https://onolys-app-staging--pr-35-kkj34ogl.web.app" ]] && ok "channel-url selects by site field (result keyed by target)" || bad "channel-url selects by site field (result keyed by target)"
bash "$PP" channel-url "$T/channel.json" other-site >/dev/null 2>&1 && bad "channel-url fails for an unknown site" || ok "channel-url fails for an unknown site"
has   "workflow reads channel url via helper"   "$WF" 'pr_preview\.sh channel-url channel\.json'
hasnt "workflow does not index .result by key"  "$WF" '\.result\[\$'
bash "$PP" tag-url https://x.run.app 0 >/dev/null 2>&1 && bad "tag-url rejects PR 0" || ok "tag-url rejects PR 0"

# --- helper: comment marker
body="$(bash "$PP" comment-body 42 https://onolys-app-staging--pr-42-abc.web.app abcdef1234567890 fake)"
first="$(printf '%s\n' "$body" | head -1)"
[[ "$first" == "<!-- onolys-pr-preview -->" ]] && ok "comment starts with marker" || bad "comment starts with marker"
[[ "$(printf '%s\n' "$body" | grep -c 'onolys-pr-preview')" == 1 ]] && ok "marker appears once" || bad "marker appears once"
for s in "https://onolys-app-staging--pr-42-abc.web.app" "abcdef1" "fake"; do
  printf '%s' "$body" | grep -qF "$s" && ok "comment contains $s" || bad "comment contains $s"
done
bash "$PP" comment-body 42 "https://x.web.app;evil" abcdef1234567890 fake >/dev/null 2>&1 && bad "rejects bad url" || ok "rejects bad url"
bash "$PP" comment-body 42 https://x.web.app abcdef1234567890 weird >/dev/null 2>&1 && bad "rejects bad mode" || ok "rejects bad mode"
bash "$PP" comment-body 42 https://x.web.app "not a sha" fake >/dev/null 2>&1 && bad "rejects bad sha" || ok "rejects bad sha"

M='<!-- onolys-pr-preview -->'
id="$(printf '[{"id":11,"body":"hi"},{"id":22,"body":"%s\\nold"},{"id":33,"body":"%s\\nlater"}]' "$M" "$M" | bash "$PP" comment-id)"
[[ "$id" == "22" ]] && ok "comment-id picks the first marker comment" || bad "comment-id picks the first marker comment (got '$id')"
id="$(printf '[{"id":11,"body":"hi"}]' | bash "$PP" comment-id)"
[[ -z "$id" ]] && ok "comment-id empty when no marker" || bad "comment-id empty when no marker (got '$id')"
id="$(printf '[]' | bash "$PP" comment-id)"
[[ -z "$id" ]] && ok "comment-id empty on empty list" || bad "comment-id empty on empty list"

# --- helper: not-found classification (cleanup ignores these, fails on anything else)
bash "$PP" is-not-found "ERROR: (gcloud.run.services.delete) Cannot find service [onolys-pr-9]" && ok "not-found: gcloud" || bad "not-found: gcloud"
bash "$PP" is-not-found "Error: Channel pr-9 does not exist on site x" && ok "not-found: firebase channel" || bad "not-found: firebase channel"
bash "$PP" is-not-found "HTTP Error: 404, Requested entity was not found." && ok "not-found: 404" || bad "not-found: 404"
bash "$PP" is-not-found "ERROR: PERMISSION_DENIED: forbidden" && bad "permission denied is not not-found" || ok "permission denied is not not-found"

# --- helper: cleanup with stubbed gcloud/npx (tag removed, only this PR's revisions deleted, not-found ignored, other errors fail)
mkdir -p "$T/bin"
# gcloud stub: behaviour comes from env vars GC_TAG_RC/GC_TAG_MSG (update-traffic), GC_REVS (revisions list), GC_DEL_RC/GC_DEL_MSG (revisions delete)
cat > "$T/bin/gcloud" <<'STUB'
#!/usr/bin/env bash
echo "gcloud $*" >> "$CALLS"
case "$*" in
  "run services update-traffic"*) [[ -n "${GC_TAG_MSG:-}" ]] && echo "$GC_TAG_MSG" >&2; exit "${GC_TAG_RC:-0}" ;;
  "run revisions list"*) printf '%s' "${GC_REVS:-}"; exit 0 ;;
  "run revisions delete"*) [[ -n "${GC_DEL_MSG:-}" ]] && echo "$GC_DEL_MSG" >&2; exit "${GC_DEL_RC:-0}" ;;
esac
exit 0
STUB
cat > "$T/bin/npx" <<'STUB'
#!/usr/bin/env bash
echo "npx $*" >> "$CALLS"
[[ -n "${NPX_MSG:-}" ]] && echo "$NPX_MSG" >&2
exit "${NPX_RC:-0}"
STUB
chmod +x "$T/bin/gcloud" "$T/bin/npx"
export CALLS="$T/calls"
run_cleanup() { : > "$CALLS"; PATH="$T/bin:$PATH" bash "$PP" cleanup "$@" >/dev/null 2>&1; }

GC_REVS=$'onolys-api-staging-pr-9-abcdef1-3-1\nonolys-api-staging-pr-9-1234567-4-1\n' run_cleanup 9 && ok "cleanup succeeds when everything exists" || bad "cleanup succeeds when everything exists"
grep -q 'gcloud run services update-traffic onolys-api-staging --remove-tags pr-9 ' "$CALLS" && ok "cleanup removes tag pr-9 from onolys-api-staging" || bad "cleanup removes tag pr-9 from onolys-api-staging"
grep -q 'gcloud run revisions list --service onolys-api-staging .*--filter metadata.name~^onolys-api-staging-pr-9-' "$CALLS" && ok "revision filter is anchored to this PR (pr-9-)" || bad "revision filter is anchored to this PR (pr-9-)"
[[ "$(grep -c 'gcloud run revisions delete' "$CALLS")" == 2 ]] && grep -q 'revisions delete onolys-api-staging-pr-9-abcdef1-3-1' "$CALLS" && grep -q 'revisions delete onolys-api-staging-pr-9-1234567-4-1' "$CALLS" && ok "cleanup deletes each listed revision" || bad "cleanup deletes each listed revision"
grep -q 'hosting:channel:delete pr-9 --site onolys-app-staging' "$CALLS" && ok "cleanup deletes the Hosting channel" || bad "cleanup deletes the Hosting channel"
grep -q 'services delete' "$CALLS" && bad "cleanup never deletes the service" || ok "cleanup never deletes the service"
# tag is removed before any revision delete
[[ "$(grep -n 'update-traffic' "$CALLS" | head -1 | cut -d: -f1)" -lt "$(grep -n 'revisions delete' "$CALLS" | head -1 | cut -d: -f1)" ]] && ok "tag removed before revisions are deleted" || bad "tag removed before revisions are deleted"
# idempotent: nothing exists
GC_TAG_RC=1 GC_TAG_MSG="ERROR: Tag [pr-9] does not exist" GC_REVS="" NPX_RC=1 NPX_MSG="Error: Channel pr-9 does not exist" run_cleanup 9 && ok "cleanup ignores not-found everywhere (idempotent)" || bad "cleanup ignores not-found everywhere (idempotent)"
GC_REVS=$'onolys-api-staging-pr-9-abcdef1-3-1\n' GC_DEL_RC=1 GC_DEL_MSG="ERROR: Revision [x] not found" run_cleanup 9 && ok "cleanup ignores a revision already gone" || bad "cleanup ignores a revision already gone"
GC_TAG_RC=1 GC_TAG_MSG="ERROR: PERMISSION_DENIED" run_cleanup 9 && bad "cleanup fails on a real tag error" || ok "cleanup fails on a real tag error"
GC_REVS=$'onolys-api-staging-pr-9-abcdef1-3-1\n' GC_DEL_RC=1 GC_DEL_MSG="ERROR: PERMISSION_DENIED" run_cleanup 9 && bad "cleanup fails on a real revision-delete error" || ok "cleanup fails on a real revision-delete error"
NPX_RC=1 NPX_MSG="Error: 500 internal" run_cleanup 9 && bad "cleanup fails on a real channel error" || ok "cleanup fails on a real channel error"
run_cleanup abc && bad "cleanup rejects bad PR number" || ok "cleanup rejects bad PR number"

command -v actionlint >/dev/null 2>&1 && { (cd "$ROOT" && actionlint "$WF" "$CL" "$DS" "$DC") && ok "actionlint" || bad "actionlint"; }
exit $fail
