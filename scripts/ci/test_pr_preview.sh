#!/usr/bin/env bash
# Guard for pr-preview.yml, pr-preview-cleanup.yml and scripts/ci/pr_preview.sh (SP00 R3). Run from anywhere.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WF="$ROOT/.github/workflows/pr-preview.yml"
PP="$ROOT/scripts/ci/pr_preview.sh"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }
has()   { grep -Eq -- "$3" "$2" 2>/dev/null && ok "$1" || bad "$1"; }
hasnt() { grep -Eq -- "$3" "$2" 2>/dev/null && bad "$1" || ok "$1"; }

for f in "$WF" "$PP"; do [[ -f "$f" ]] && ok "exists: ${f#"$ROOT"/}" || { bad "exists: ${f#"$ROOT"/}"; }; done
[[ -f "$WF" && -f "$PP" ]] || exit 1

# --- pr-preview.yml
has   "triggers: opened, synchronize, reopened" "$WF" 'types: \[opened, synchronize, reopened\]'
has   "same-repo guard"                         "$WF" 'github\.event\.pull_request\.head\.repo\.full_name == github\.repository'
has   "concurrency per PR number"               "$WF" 'group: pr-preview-\$\{\{ github\.event\.number \}\}'
has   "cancel-in-progress true"                 "$WF" 'cancel-in-progress: true'
has   "WIF auth"                                "$WF" 'google-github-actions/auth@v2'
has   "deployer-staging SA var"                 "$WF" 'vars\.DEPLOYER_STAGING_SA'
hasnt "no JSON key auth"                        "$WF" 'credentials_json|GOOGLE_CREDENTIALS|service_account_key'
has   "image tag pr-<N>-<sha>"                  "$WF" 'pr-\$\{\{ github\.event\.number \}\}-'
has   "service onolys-pr-<N>"                   "$WF" 'onolys-pr-'
has   "combined mode"                           "$WF" 'SERVICE_MODE=combined'
has   "fake adapters by default (adapters=stub)" "$WF" 'adapters=stub; mode=fake'
has   "staging database"                        "$WF" 'FIRESTORE_DATABASE=staging'
has   "GIT_SHA set"                             "$WF" 'GIT_SHA='
has   "max 1 instance"                          "$WF" '--max-instances[ =]1'
has   "min 0 instances"                         "$WF" '--min-instances[ =]0'
has   "CPU always allocated"                    "$WF" '--no-cpu-throttling'
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

# --- helper: firebase-config
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
bash "$PP" firebase-config 42 "$ROOT/web/firebase.json" "$T/fb.json" >/dev/null 2>&1 && ok "firebase-config runs" || bad "firebase-config runs"
python3 - "$T/fb.json" <<'PY' && ok "config: /v1/** -> onolys-pr-42 before SPA fallback, target app-staging only" || bad "config: /v1/** -> onolys-pr-42 before SPA fallback, target app-staging only"
import json, sys
c = json.load(open(sys.argv[1]))
h = c["hosting"]
assert len(h) == 1 and h[0]["target"] == "app-staging", h
r = h[0]["rewrites"]
assert r[0]["source"] == "/v1/**" and r[0]["run"]["serviceId"] == "onolys-pr-42", r
assert r[0]["run"]["region"] == "us-central1", r
assert r[-1] == {"source": "**", "destination": "/index.html"}, r
assert h[0]["public"] == "dist"
assert any("Content-Security-Policy" == x["key"] for g in h[0]["headers"] for x in g["headers"])
PY
grep -q 'onolys-api-' "$T/fb.json" && bad "no staging/prod service left in config" || ok "no staging/prod service left in config"
for n in "" abc "4;2" "-1" "0"; do
  bash "$PP" firebase-config "$n" "$ROOT/web/firebase.json" "$T/x.json" >/dev/null 2>&1 && bad "rejects PR number '$n'" || ok "rejects PR number '$n'"
done
echo '{"hosting":[{"target":"other","rewrites":[]}]}' > "$T/nofb.json"
bash "$PP" firebase-config 7 "$T/nofb.json" "$T/x.json" >/dev/null 2>&1 && bad "fails without app-staging target" || ok "fails without app-staging target"
echo '{"hosting":[{"target":"app-staging","rewrites":[{"source":"**","destination":"/index.html"}]}]}' > "$T/norw.json"
bash "$PP" firebase-config 7 "$T/norw.json" "$T/x.json" >/dev/null 2>&1 && bad "fails without /v1/** rewrite" || ok "fails without /v1/** rewrite"

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

command -v actionlint >/dev/null 2>&1 && { (cd "$ROOT" && actionlint "$WF") && ok "actionlint" || bad "actionlint"; }
exit $fail
