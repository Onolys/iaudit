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
has   "restore step runs pr_preview.sh restore-template" "$WF" 'pr_preview\.sh restore-template "\$PR"'
has   "restore step runs even if the deploy step failed (always, but not when it never started)" "$WF" "always\(\) && steps\.run\.outcome != 'skipped'"
has   "restore step gets project/region for the helper" "$WF" 'GCP_REGION: \$\{\{ env\.REGION \}\}'
rl="$(grep -n 'run: bash scripts/ci/pr_preview\.sh restore-template' "$WF" | head -1 | cut -d: -f1)"; dl="$(grep -n 'gcloud run deploy' "$WF" | head -1 | cut -d: -f1)"; sl="$(grep -n 'name: Smoke the tag URL' "$WF" | head -1 | cut -d: -f1)"
[[ -n "$rl" && -n "$dl" && -n "$sl" && "$dl" -lt "$rl" && "$rl" -lt "$sl" ]] && ok "restore step sits between the deploy and the smoke test" || bad "restore step sits between the deploy and the smoke test"
hasnt "restore never moves traffic (no update-traffic/--to-* in the workflow)" "$WF" 'update-traffic|--to-latest|--to-revisions'
has   "cleanup restores the template (helper)" "$PP" 'restore_template "\$pr"'
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
cat > "$T/bin/curl" <<'STUB'
#!/usr/bin/env bash
# curl stub for the Cloud Run v2 API: -X METHOD ... URL. Files: CURL_SVC, CURL_REV (GET), CURL_PATCH_RC/CURL_PATCH_MSG, CURL_OP (operation poll)
echo "curl $*" >> "$CALLS"
method=GET; url=""; body=""
while [[ $# -gt 0 ]]; do case "$1" in -X) method="$2"; shift 2 ;; -d) body="$2"; shift 2 ;; -H) shift 2 ;; -*) shift ;; *) url="$1"; shift ;; esac; done
case "$method $url" in
  "GET "*/revisions/*) cat "${CURL_REV:?}" ;;
  "GET "*/operations/*) echo '{"error":{"code":403,"status":"PERMISSION_DENIED"}}'; exit 22 ;;  # the deployer SA may not read operations
  "GET "*/services/*) if [[ -e "$PATCH_BODY" ]]; then cat "${CURL_POLL:-$CURL_SVC}"; else cat "${CURL_SVC:?}"; fi ;;  # after the PATCH: the polled service
  "PATCH "*) echo "$url" > "$PATCH_URL"
    if [[ "${CURL_PATCH_RC:-0}" != 0 ]]; then printf '%s\n' "${CURL_PATCH_MSG:-error}"; exit "$CURL_PATCH_RC"; fi
    printf '%s' "$body" > "$PATCH_BODY"
    printf '{"name":"projects/onolys/locations/us-central1/operations/op1","metadata":{"generation":"%s"}}' "${CURL_PATCH_GEN:-7}" ;;
esac
exit 0
STUB
chmod +x "$T/bin/curl"
export PATCH_BODY="$T/patch_body" PATCH_URL="$T/patch_url" RESTORE_POLL_SLEEP=0 RESTORE_RETRY_SLEEP=0
# fixtures: serving revision R7 (real/api), service template either equal to it (clean) or the preview config
SRV=onolys-api-staging-abc1234-7-1; PRV=onolys-api-staging-pr-42-fc89744-14-1
jq -n --arg n "projects/onolys/locations/us-central1/services/onolys-api-staging/revisions/$SRV" '{name:$n,uid:"u1",generation:"1",createTime:"t",logUri:"l",conditions:[],observedGeneration:"1",
  labels:{"managed-by":"github-actions","cloud.googleapis.com/location":"us-central1","run.googleapis.com/startupProbeType":"Default"},annotations:{"run.googleapis.com/client-name":"gcloud","autoscaling.knative.dev/maxScale":"3","serving.knative.dev/creator":"d@x","client.knative.dev/user-image":"i","team":"keep"},scaling:{maxInstanceCount:3},timeout:"60s",serviceAccount:"api-staging@onolys.iam.gserviceaccount.com",maxInstanceRequestConcurrency:80,client:"gcloud",
  containers:[{name:"api-1",image:"r/api@sha256:aaa",env:[{name:"ADAPTERS",value:"real"},{name:"SERVICE_MODE",value:"api"},{name:"GIT_SHA",value:"abc1234"}],resources:{limits:{cpu:"1"},cpuIdle:true}}]}' > "$T/rev.json"
mk_svc() {  # mk_svc <clean|preview> [serving revision name or "none"] [template revision name]
  jq --arg rname "${3:-}" --arg mode "$1" --arg srv "${2:-$SRV}" --arg prv "$PRV" '{etag:"\"e1\"",
    traffic:([{type:"TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION",revision:$srv,percent:100},{type:"TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION",revision:$prv,percent:0,tag:"pr-42"}] | if $srv=="none" then map(select(.percent==0)) else . end),
    template:(del(.name,.uid,.generation,.createTime,.logUri,.conditions,.observedGeneration,.client) | .labels |= with_entries(select(.key | test("/") | not)) | .annotations |= with_entries(select(.key | test("/") | not)) | . + {revision:(if $rname == "" then $prv else $rname end)}
      | .containers[0] |= (del(.name) | .image="r/api@sha256:bbb")
      | if $mode=="preview" then .containers[0].env=[{name:"ADAPTERS",value:"stub"},{name:"SERVICE_MODE",value:"combined"},{name:"GIT_SHA",value:"fc89744"}] | .containers[0].resources.cpuIdle=false else . end)}' "$T/rev.json" 
}
mk_gen() { jq --arg g "$1" --arg r "$2" --arg c "$3" '. + {generation:$g, observedGeneration:$r, terminalCondition:{type:"Ready",state:$c}}' "$T/svc_clean.json"; }
mk_svc clean > "$T/svc_clean.json"; mk_gen 7 7 CONDITION_SUCCEEDED > "$T/svc_done.json"; mk_gen 7 6 CONDITION_RECONCILING > "$T/svc_pending.json"; mk_gen 7 7 CONDITION_FAILED > "$T/svc_failed.json"; mk_gen 9 9 CONDITION_SUCCEEDED > "$T/svc_newer.json"; mk_svc preview > "$T/svc_preview.json"; mk_svc preview none > "$T/svc_notraffic.json"
mk_svc preview "$SRV" onolys-api-staging-def5678-9-1 > "$T/svc_maindeploy.json"      # main deploy gap: template = NEW release, traffic still on the old revision
mk_svc preview "$SRV" onolys-api-staging-pr-42-tpl-1795284254 > "$T/svc_tplname.json" # already restored once
jq '. + {reconciling:true}' "$T/svc_preview.json" > "$T/svc_reconciling.json"
export CURL_REV="$T/rev.json" CURL_SVC="$T/svc_clean.json" CURL_POLL="$T/svc_done.json"
run_restore() { : > "$CALLS"; rm -f "$PATCH_BODY" "$PATCH_URL"; PATH="$T/bin:$PATH" bash "$PP" restore-template "$@" >"$T/restore.out" 2>&1; }

run_cleanup() { : > "$CALLS"; rm -f "$PATCH_BODY" "$PATCH_URL"; PATH="$T/bin:$PATH" bash "$PP" cleanup "$@" >/dev/null 2>&1; }

# --- restore-template: the staging service template goes back to the serving revision; traffic is never part of the write
CURL_SVC="$T/svc_clean.json" run_restore 42 && ok "restore: clean template succeeds" || bad "restore: clean template succeeds"
[[ ! -e "$PATCH_BODY" ]] && ok "restore: no PATCH when the template already matches (image digest form ignored)" || bad "restore: no PATCH when the template already matches"
CURL_SVC="$T/svc_preview.json" run_restore 42 && ok "restore: preview template succeeds" || { bad "restore: preview template succeeds"; cat "$T/restore.out"; }
[[ "$(grep -c '^curl .*-X PATCH' "$CALLS")" == 1 ]] && ok "restore: exactly one PATCH" || bad "restore: exactly one PATCH"
grep -q 'services/onolys-api-staging?updateMask=template$' "$PATCH_URL" && ok "restore: updateMask is template only (traffic untouched)" || bad "restore: updateMask is template only ($(cat "$PATCH_URL" 2>/dev/null))"
jq -e '.template.containers[0].env | (map(select(.name=="ADAPTERS").value)==["real"]) and (map(select(.name=="SERVICE_MODE").value)==["api"]) and (map(select(.name=="GIT_SHA").value)==["abc1234"])' "$PATCH_BODY" >/dev/null && ok "restore: body env is the serving revision's (real/api/GIT_SHA)" || bad "restore: body env is the serving revision's"
jq -e '.template.containers[0].resources.cpuIdle == true and .template.scaling.maxInstanceCount == 3 and .template.serviceAccount != null' "$PATCH_BODY" >/dev/null && ok "restore: body cpuIdle/scaling/serviceAccount from the serving revision" || bad "restore: body cpuIdle/scaling/serviceAccount"
jq -e '(.template.revision | test("^onolys-api-staging-pr-42-tpl-[0-9]+$")) and .etag == "\"e1\"" and (has("traffic") | not) and (.template | has("name","uid","conditions","logUri") | not)' "$PATCH_BODY" >/dev/null && ok "restore: new revision name pr-42-tpl-<epoch>, service etag, no traffic key, no output-only fields" || bad "restore: body shape ($(cat "$PATCH_BODY"))"
CURL_SVC="$T/svc_preview.json" run_restore && jq -e '.template.revision | test("^onolys-api-staging-pr-0-tpl-")' "$PATCH_BODY" >/dev/null && ok "restore: PR argument optional" || bad "restore: PR argument optional"
CURL_SVC="$T/svc_notraffic.json" run_restore 42 && bad "restore: refuses when no revision serves traffic" || ok "restore: refuses when no revision serves traffic"
[[ ! -e "$PATCH_BODY" ]] && ok "restore: no PATCH when no revision serves traffic" || bad "restore: no PATCH when no revision serves traffic"
CURL_SVC="$T/svc_preview.json" CURL_PATCH_RC=22 CURL_PATCH_MSG='{"error":{"code":409,"status":"ABORTED"}}' run_restore 42 && bad "restore: persistent etag conflict fails" || ok "restore: persistent etag conflict fails"
[[ "$(grep -c '^curl .*-X PATCH' "$CALLS")" == 3 ]] && ok "restore: etag conflict retried (3 attempts, re-read each time)" || bad "restore: etag conflict retried"
CURL_SVC="$T/svc_preview.json" CURL_PATCH_RC=22 CURL_PATCH_MSG='{"error":{"code":403,"status":"PERMISSION_DENIED"}}' run_restore 42 && bad "restore: permission error fails" || ok "restore: permission error fails"
[[ "$(grep -c '^curl .*-X PATCH' "$CALLS")" == 1 ]] && ok "restore: non-conflict error not retried" || bad "restore: non-conflict error not retried"
CURL_SVC="$T/svc_preview.json" CURL_POLL="$T/svc_failed.json" run_restore 42 && bad "restore: failed service condition fails" || ok "restore: failed service condition fails"
CURL_SVC="$T/svc_preview.json" CURL_POLL="$T/svc_pending.json" RESTORE_POLLS=2 run_restore 42 && bad "restore: service still reconciling (observedGeneration < generation) fails at timeout" || ok "restore: service still reconciling fails at timeout"
CURL_SVC="$T/svc_preview.json" CURL_POLL="$T/svc_newer.json" run_restore 42 && ok "restore: newer observed generation (concurrent update) counts as done" || bad "restore: newer observed generation counts as done"
grep -q '/operations/' "$CALLS" && bad "restore: never polls the operations endpoint (no IAM for it)" || ok "restore: never polls the operations endpoint"
CURL_SVC="$T/svc_preview.json" run_restore 42 && ok "restore: done once observedGeneration >= PATCH generation and Ready" || bad "restore: done once observedGeneration >= PATCH generation"
grep -q '/operations/' "$CALLS" && bad "restore: success path polls no operation" || ok "restore: success path polls no operation"
run_restore abc && bad "restore: rejects bad PR number" || ok "restore: rejects bad PR number"
# review fixes: restore only a preview template (a main deploy's template must never be rolled back), never while reconciling
CURL_SVC="$T/svc_maindeploy.json" run_restore 42 && ok "restore: main-named template (deploy gap) is left alone" || bad "restore: main-named template left alone (rc)"
[[ ! -e "$PATCH_BODY" ]] && ok "restore: no PATCH when the template revision is not a preview revision" || bad "restore: no PATCH when the template revision is not a preview revision"
CURL_SVC="$T/svc_tplname.json" run_restore 42 && [[ ! -e "$PATCH_BODY" ]] && ok "restore: no PATCH when the template is already a -tpl- restore revision" || bad "restore: no PATCH for -tpl- template"
CURL_SVC="$T/svc_reconciling.json" run_restore 42 && [[ ! -e "$PATCH_BODY" ]] && ok "restore: no PATCH while the service is reconciling" || bad "restore: no PATCH while reconciling"
# system labels/annotations: stripped from the write and from the comparison
CURL_SVC="$T/svc_clean.json" run_restore 42; [[ ! -e "$PATCH_BODY" ]] && ok "restore: system labels/annotations on the revision do not cause a permanent mismatch" || bad "restore: system keys cause mismatch"
CURL_SVC="$T/svc_preview.json" run_restore 42
jq -e '[.template.labels, .template.annotations | keys[]] | (map(test("^(serving|cloud|run|autoscaling|client)\\.(knative\\.dev|googleapis\\.com)/")) | any | not) and (index("team") != null) and (index("managed-by") != null)' "$PATCH_BODY" >/dev/null && ok "restore: PATCH body has no system label/annotation keys, keeps user ones" || bad "restore: system keys in PATCH body ($(jq -c '[.template.labels,.template.annotations]' "$PATCH_BODY" 2>/dev/null))"
grep -q 'Authorization: Bearer' "$CALLS" && bad "restore: bearer token not in curl argv" || ok "restore: bearer token not in curl argv (stdin header)"
# cleanup restores before deleting revisions, and fails when the restore fails
GC_REVS=$'onolys-api-staging-pr-42-fc89744-14-1\n' CURL_SVC="$T/svc_preview.json" run_cleanup 42 && ok "cleanup with preview template succeeds" || bad "cleanup with preview template succeeds"
pl="$(grep -n '^curl .*-X PATCH' "$CALLS" | head -1 | cut -d: -f1)"; dl2="$(grep -n 'revisions delete' "$CALLS" | head -1 | cut -d: -f1)"
[[ -n "$pl" && -n "$dl2" && "$pl" -lt "$dl2" ]] && ok "cleanup restores the template before deleting revisions" || bad "cleanup restores the template before deleting revisions"
GC_REVS="" CURL_SVC="$T/svc_notraffic.json" run_cleanup 42 && bad "cleanup fails when restore fails" || ok "cleanup fails when restore fails"
GC_REVS="" CURL_SVC="$T/svc_clean.json" run_cleanup 42 && ok "cleanup with clean template succeeds (restore is a no-op)" || bad "cleanup with clean template succeeds"

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

# --- cleanup: latest-created-revision rule (live run 44844909790) and sweep
LATEST_MSG="ERROR: (gcloud.run.revisions.delete) FAILED_PRECONDITION: The latest created Revision onolys-api-staging-pr-9-abcdef1-3-1 cannot be directly deleted."
GC_REVS=$'onolys-api-staging-pr-9-abcdef1-3-1\n' GC_DEL_RC=1 GC_DEL_MSG="$LATEST_MSG" run_cleanup 9 && ok "cleanup exits 0 when the only error is the latest-revision rule" || bad "cleanup exits 0 when the only error is the latest-revision rule"
grep -q 'hosting:channel:delete pr-9 --site onolys-app-staging' "$CALLS" && ok "channel still deleted after the latest-revision error" || bad "channel still deleted after the latest-revision error"
out="$(GC_REVS=$'onolys-api-staging-pr-9-abcdef1-3-1\n' GC_DEL_RC=1 GC_DEL_MSG="$LATEST_MSG" PATH="$T/bin:$PATH" bash "$PP" cleanup 9 2>&1)"
printf '%s' "$out" | grep -q 'left for sweep: onolys-api-staging-pr-9-abcdef1-3-1' && ok "logs 'left for sweep: <rev>'" || bad "logs 'left for sweep: <rev>'"
# real revision error: channel is still attempted, exit non-zero
GC_REVS=$'onolys-api-staging-pr-9-abcdef1-3-1\n' GC_DEL_RC=1 GC_DEL_MSG="ERROR: PERMISSION_DENIED" run_cleanup 9 && bad "real revision error still exits non-zero" || ok "real revision error still exits non-zero"
grep -q 'hosting:channel:delete pr-9' "$CALLS" && ok "channel attempted even after a real revision error" || bad "channel attempted even after a real revision error"
GC_TAG_RC=1 GC_TAG_MSG="ERROR: PERMISSION_DENIED" run_cleanup 9; grep -q 'hosting:channel:delete pr-9' "$CALLS" && ok "channel attempted even after a real tag error" || bad "channel attempted even after a real tag error"

# sweep: stub describe returns service JSON (GC_SVC). latest = pr-9-...-latest; pr-3 untagged old, pr-35 tagged (open PR), pr-3x anchoring, non-pr revision.
SVC='{"status":{"latestCreatedRevisionName":"onolys-api-staging-pr-9-ffffff1-9-1","traffic":[{"revisionName":"onolys-api-staging-abcdef1-7-1","percent":100},{"revisionName":"onolys-api-staging-pr-35-1111111-2-1","percent":0,"tag":"pr-35"}]}}'
REVS=$'onolys-api-staging-abcdef1-7-1\nonolys-api-staging-pr-3-2222222-1-1\nonolys-api-staging-pr-35-1111111-2-1\nonolys-api-staging-pr-9-ffffff1-9-1\nonolys-api-staging-pr-12-3333333-4-1\nonolys-api-staging-prod-x-1\n'
cat > "$T/bin/gcloud" <<'STUB'
#!/usr/bin/env bash
echo "gcloud $*" >> "$CALLS"
case "$*" in
  "run services update-traffic"*) [[ -n "${GC_TAG_MSG:-}" ]] && echo "$GC_TAG_MSG" >&2; exit "${GC_TAG_RC:-0}" ;;
  "run services describe"*) printf '%s' "${GC_SVC:-}"; exit 0 ;;
  "run revisions list"*) printf '%s' "${GC_REVS:-}"; exit 0 ;;
  "run revisions delete"*) [[ -n "${GC_DEL_MSG:-}" ]] && echo "$GC_DEL_MSG" >&2; exit "${GC_DEL_RC:-0}" ;;
esac
exit 0
STUB
run_sweep() { : > "$CALLS"; PATH="$T/bin:$PATH" bash "$PP" sweep >/dev/null 2>&1; }
GC_SVC="$SVC" GC_REVS="$REVS" run_sweep && ok "sweep succeeds" || bad "sweep succeeds"
deleted="$(grep -o 'revisions delete [^ ]*' "$CALLS" | awk '{print $3}' | sort | tr '\n' ' ')"
[[ "$deleted" == "onolys-api-staging-pr-12-3333333-4-1 onolys-api-staging-pr-3-2222222-1-1 " ]] && ok "sweep deletes only untagged, non-latest, 0% pr revisions" || bad "sweep deletes only untagged non-latest pr revisions (got: $deleted)"
grep -q 'revisions list .*--filter metadata.name~^onolys-api-staging-pr-\[0-9\]+-' "$CALLS" && ok "sweep filter anchored: pr-<digits>-" || bad "sweep filter anchored: pr-<digits>-"
GC_SVC="" GC_REVS="$REVS" run_sweep && bad "sweep refuses when service state is unknown" || ok "sweep refuses when service state is unknown"
grep -q 'revisions delete' "$CALLS" && bad "sweep deletes nothing when state unknown" || ok "sweep deletes nothing when state unknown"
GC_SVC="$SVC" GC_REVS=$'onolys-api-staging-pr-3-2222222-1-1\n' GC_DEL_RC=1 GC_DEL_MSG="$LATEST_MSG" run_sweep && ok "sweep tolerates the latest-revision error" || bad "sweep tolerates the latest-revision error"
# pr-3 cleanup must not touch pr-35 (filter anchored with trailing dash)
: > "$CALLS"; GC_REVS="" PATH="$T/bin:$PATH" bash "$PP" cleanup 3 >/dev/null 2>&1
grep -q 'metadata.name~^onolys-api-staging-pr-3-' "$CALLS" && ! grep -q 'pr-35' "$CALLS" && ok "cleanup 3 filter anchored (cannot match pr-35)" || bad "cleanup 3 filter anchored (cannot match pr-35)"
# cleanup ends with a sweep (non-fatal)
GC_SVC="$SVC" GC_REVS=$'onolys-api-staging-pr-3-2222222-1-1\n' run_cleanup 7; grep -q 'run services describe' "$CALLS" && ok "cleanup runs a sweep at the end" || bad "cleanup runs a sweep at the end"
GC_SVC="not json" GC_REVS="" run_cleanup 7 && ok "sweep failure inside cleanup is non-fatal" || bad "sweep failure inside cleanup is non-fatal"
has   "deploy-staging runs sweep after api deploy" "$DS" 'pr_preview\.sh sweep'

command -v actionlint >/dev/null 2>&1 && { (cd "$ROOT" && actionlint "$WF" "$CL" "$DS" "$DC") && ok "actionlint" || bad "actionlint"; }
exit $fail
