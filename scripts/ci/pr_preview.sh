#!/usr/bin/env bash
# Helpers for pr-preview.yml / pr-preview-cleanup.yml (SP00 R3). Pure functions, no cloud calls except `cleanup`.
#   pr_preview.sh firebase-config <pr> <src firebase.json> <out>   Hosting config: /v1/** -> onolys-pr-<pr>, target app-staging only
#   pr_preview.sh env-file <adapters> <sha> <out>                  YAML for `gcloud run deploy --env-vars-file` (values may hold @ and ,)
#   pr_preview.sh comment-body <pr> <url> <sha> <fake|real>        marker PR comment body
#   pr_preview.sh comment-id                                        stdin: JSON list of PR comments -> id of the first marker comment (or empty)
#   pr_preview.sh comment <pr> <url> <sha> <mode>                   create-or-update the ONE marker comment (needs gh, GITHUB_REPOSITORY, GH_TOKEN)
#   pr_preview.sh is-not-found <text>                               exit 0 when text looks like a not-found error
#   pr_preview.sh cleanup <pr>                                      delete Cloud Run service + Hosting channel, ignoring not-found
set -euo pipefail
MARKER='<!-- onolys-pr-preview -->'
REGION="${GCP_REGION:-us-central1}"
PROJECT="${GCP_PROJECT:-onolys}"
SITE="${PREVIEW_SITE:-onolys-app-staging}"
FIREBASE_TOOLS_VERSION="${FIREBASE_TOOLS_VERSION:-15.37.0}"

die() { echo "pr_preview.sh: $*" >&2; exit 1; }
need_pr() { [[ "${1:-}" =~ ^[1-9][0-9]*$ ]] || die "PR number must be a positive integer: '${1:-}'"; }

firebase_config() {
  local pr="${1:-}" src="${2:-}" out="${3:-}"
  need_pr "$pr"; [[ -f "$src" ]] || die "no such file: $src"; [[ -n "$out" ]] || die "output path required"
  python3 - "$pr" "$src" "$out" "$REGION" <<'PY'
import json, sys
pr, src, out, region = sys.argv[1:5]
site = next((h for h in json.load(open(src)).get("hosting", []) if h.get("target") == "app-staging"), None)
if site is None:
    sys.exit("no hosting target app-staging in " + src)
rewrites = site.get("rewrites", [])
idx = next((i for i, r in enumerate(rewrites) if r.get("source") == "/v1/**" and "run" in r), None)
if idx is None:
    sys.exit("no /v1/** Cloud Run rewrite in target app-staging")
rewrites[idx]["run"] = {"serviceId": f"onolys-pr-{pr}", "region": region}
if idx != 0 and any(r.get("source") == "**" for r in rewrites[:idx]):
    sys.exit("SPA fallback precedes /v1/**")
json.dump({"hosting": [site]}, open(out, "w"), indent=2)
PY
}

env_file() {
  local adapters="${1:-}" sha="${2:-}" out="${3:-}"
  [[ "$adapters" =~ ^[a-z]+$ ]] || die "bad adapters: '$adapters'"
  [[ "$sha" =~ ^[0-9a-f]{7,40}$ ]] || die "bad sha: '$sha'"
  [[ -n "$out" ]] || die "output path required"
  # JSON is valid YAML; json.dumps quotes every value, so '@', ',' and ':' stay literal.
  python3 - "$adapters" "$sha" "$out" "$PROJECT" "$REGION" <<'PY'
import json, sys
adapters, sha, out, project, region = sys.argv[1:6]
env = {
    "ENV": "staging", "SERVICE_MODE": "combined", "ADAPTERS": adapters, "FIRESTORE_DATABASE": "staging",
    "GCP_PROJECT": project, "AUTH_PROJECT": project, "REGION": region,
    "AUDIO_BUCKET": "onolys-audio-staging",
    "BLOB_SIGNER_EMAIL": f"api-staging@{project}.iam.gserviceaccount.com",
    "ROUTES_FILE": "config/staging/routes.yaml", "DAILY_RUN_CAP": "20",
    "CORS_ORIGINS": "http://localhost:5173", "GIT_SHA": sha,
}
json.dump(env, open(out, "w"), indent=2)
PY
}

comment_body() {
  local pr="${1:-}" url="${2:-}" sha="${3:-}" mode="${4:-}"
  need_pr "$pr"
  [[ "$url" =~ ^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~/-]*)?$ ]] || die "bad url: '$url'"
  [[ "$sha" =~ ^[0-9a-f]{7,40}$ ]] || die "bad sha: '$sha'"
  case "$mode" in fake|real) ;; *) die "mode must be fake or real: '$mode'" ;; esac
  printf '%s\n' "$MARKER"
  printf '### PR preview\n\n'
  printf '| | |\n|---|---|\n'
  printf '| Preview | %s |\n' "$url"
  printf '| Commit | `%s` |\n' "${sha:0:7}"
  printf '| Mode | %s adapters |\n' "$mode"
  printf '| Backend | Cloud Run `onolys-pr-%s` (staging database) |\n\n' "$pr"
  printf 'Updated on every push; the channel expires 7 days after the last deploy and is deleted when the PR closes.\n'
}

comment_id() {
  jq -r --arg m "$MARKER" '[.[] | select((.body // "") | contains($m))][0].id // empty'
}

post_comment() {
  local pr="${1:-}"; shift
  [[ -n "${GITHUB_REPOSITORY:-}" ]] || die "GITHUB_REPOSITORY required"
  local body id
  body="$(comment_body "$pr" "$@")"
  id="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/issues/${pr}/comments" | jq -s 'add // []' | comment_id)"
  if [[ -n "$id" ]]; then
    gh api -X PATCH "repos/${GITHUB_REPOSITORY}/issues/comments/${id}" -f body="$body" >/dev/null
    echo "updated comment $id"
  else
    gh api -X POST "repos/${GITHUB_REPOSITORY}/issues/${pr}/comments" -f body="$body" >/dev/null
    echo "created comment"
  fi
}

is_not_found() {
  printf '%s' "${1:-}" | grep -Eiq 'not[ _-]?found|cannot find|does not exist|could not be found|HTTP Error: 404|\b404\b'
}

# Run a delete command; succeed on not-found, fail on any other error.
delete_ignoring_not_found() {
  local what="$1"; shift
  local out rc=0
  out="$("$@" 2>&1)" || rc=$?
  printf '%s\n' "$out"
  if [[ $rc -ne 0 ]]; then
    if is_not_found "$out"; then echo "$what: already gone (ignored)"; else die "$what: delete failed"; fi
  fi
}

cleanup() {
  local pr="${1:-}"; need_pr "$pr"
  delete_ignoring_not_found "Cloud Run service onolys-pr-$pr" \
    gcloud run services delete "onolys-pr-$pr" --region "$REGION" --project "$PROJECT" --quiet
  delete_ignoring_not_found "Hosting channel pr-$pr" \
    npx --yes "firebase-tools@${FIREBASE_TOOLS_VERSION}" hosting:channel:delete "pr-$pr" --site "$SITE" --project "$PROJECT" --force --non-interactive
}

cmd="${1:-}"; [[ $# -gt 0 ]] && shift
case "$cmd" in
  firebase-config) firebase_config "$@" ;;
  env-file)        env_file "$@" ;;
  comment-body)    comment_body "$@" ;;
  comment-id)      comment_id ;;
  comment)         post_comment "$@" ;;
  is-not-found)    is_not_found "$@" ;;
  cleanup)         cleanup "$@" ;;
  *) die "usage: pr_preview.sh firebase-config|env-file|comment-body|comment-id|comment|is-not-found|cleanup ..." ;;
esac
