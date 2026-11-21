#!/usr/bin/env bash
# Helpers for pr-preview.yml / pr-preview-cleanup.yml (SP00 R3). Pure functions, no cloud calls except `cleanup`.
#   pr_preview.sh firebase-config <api origin> <src firebase.json> <out>   Hosting config: target app-staging only, no /v1/** rewrite
#                                                                          (the web build calls the tag URL directly), API origin added to CSP connect-src
#   pr_preview.sh env-overrides <adapters> <sha> <cors origin>     value for `gcloud run deploy --update-env-vars` (custom `^|^` delimiter)
#   pr_preview.sh tag-url <service url> <pr>                       https://pr-<pr>---<service host>
#   pr_preview.sh comment-body <pr> <url> <sha> <fake|real>        marker PR comment body
#   pr_preview.sh comment-id                                        stdin: JSON list of PR comments -> id of the first marker comment (or empty)
#   pr_preview.sh comment <pr> <url> <sha> <mode>                   create-or-update the ONE marker comment (needs gh, GITHUB_REPOSITORY, GH_TOKEN)
#   pr_preview.sh is-not-found <text>                               exit 0 when text looks like a not-found error
#   pr_preview.sh cleanup <pr>                                      remove tag pr-<pr> + delete its revisions on the staging API service, delete the Hosting channel (not-found ignored)
set -euo pipefail
MARKER='<!-- onolys-pr-preview -->'
REGION="${GCP_REGION:-us-central1}"
PROJECT="${GCP_PROJECT:-onolys}"
SITE="${PREVIEW_SITE:-onolys-app-staging}"
SERVICE="${PREVIEW_SERVICE:-onolys-api-staging}"
FIREBASE_TOOLS_VERSION="${FIREBASE_TOOLS_VERSION:-15.37.0}"

die() { echo "pr_preview.sh: $*" >&2; exit 1; }
need_pr() { [[ "${1:-}" =~ ^[1-9][0-9]*$ ]] || die "PR number must be a positive integer: '${1:-}'"; }

firebase_config() {
  local api="${1:-}" src="${2:-}" out="${3:-}"
  [[ "$api" =~ ^https://[A-Za-z0-9.-]+$ ]] || die "api origin must be https://host: '$api'"
  [[ -f "$src" ]] || die "no such file: $src"; [[ -n "$out" ]] || die "output path required"
  python3 - "$api" "$src" "$out" <<'PY'
import json, sys
api, src, out = sys.argv[1:4]
site = next((h for h in json.load(open(src)).get("hosting", []) if h.get("target") == "app-staging"), None)
if site is None:
    sys.exit("no hosting target app-staging in " + src)
# Hosting cannot rewrite to a Cloud Run tag, so the preview web build calls the tag URL directly (cross-origin).
# Drop the /v1/** rewrite (it would target the live staging revision) and allow the tag origin in the CSP.
site["rewrites"] = [r for r in site.get("rewrites", []) if "run" not in r]
if not any(r.get("source") == "**" for r in site["rewrites"]):
    sys.exit("no SPA fallback rewrite in target app-staging")
n = 0
for g in site.get("headers", []):
    for h in g.get("headers", []):
        if h.get("key") == "Content-Security-Policy" and "connect-src" in h["value"]:
            h["value"] = h["value"].replace("connect-src", "connect-src " + api, 1)
            n += 1
if n != 1:
    sys.exit(f"expected exactly one CSP connect-src, found {n}")
json.dump({"hosting": [site]}, open(out, "w"), indent=2)
PY
}

# Overrides for the preview revision only. They are written into the service template by `gcloud run deploy`, which is why
# deploy-staging.yml re-specifies every key listed here (see _deploy-cloudrun.yml inputs env_vars / flags).
env_overrides() {
  local adapters="${1:-}" sha="${2:-}" cors="${3:-}"
  [[ "$adapters" =~ ^[a-z]+$ ]] || die "bad adapters: '$adapters'"
  [[ "$sha" =~ ^[0-9a-f]{7,40}$ ]] || die "bad sha: '$sha'"
  [[ "$cors" =~ ^https://[A-Za-z0-9.-]+$ ]] || die "bad cors origin: '$cors'"
  printf '^|^SERVICE_MODE=combined|ADAPTERS=%s|GIT_SHA=%s|CORS_ORIGINS=%s\n' "$adapters" "$sha" "$cors"
}

tag_url() {
  local url="${1:-}" pr="${2:-}"; need_pr "$pr"
  [[ "$url" =~ ^https://[A-Za-z0-9.-]+/?$ ]] || die "bad service url: '$url'"
  url="${url%/}"
  printf 'https://pr-%s---%s\n' "$pr" "${url#https://}"
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
  printf '| Backend | Cloud Run `onolys-api-staging` tag `pr-%s` (no traffic, staging database) |\n\n' "$pr"
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
  delete_ignoring_not_found "Cloud Run tag pr-$pr" \
    gcloud run services update-traffic "$SERVICE" --remove-tags "pr-$pr" --region "$REGION" --project "$PROJECT" --quiet
  # Tag first: a revision that still carries a tag (or traffic) cannot be deleted. Revision names: <service>-pr-<N>-<sha7>-<run>-<attempt>.
  local names rev
  names="$(gcloud run revisions list --service "$SERVICE" --region "$REGION" --project "$PROJECT" \
    --filter "metadata.name~^${SERVICE}-pr-${pr}-" --format 'value(metadata.name)')" || die "listing revisions failed"
  for rev in $names; do
    delete_ignoring_not_found "Cloud Run revision $rev" \
      gcloud run revisions delete "$rev" --region "$REGION" --project "$PROJECT" --quiet
  done
  delete_ignoring_not_found "Hosting channel pr-$pr" \
    npx --yes "firebase-tools@${FIREBASE_TOOLS_VERSION}" hosting:channel:delete "pr-$pr" --site "$SITE" --project "$PROJECT" --force --non-interactive
}

cmd="${1:-}"; [[ $# -gt 0 ]] && shift
case "$cmd" in
  firebase-config) firebase_config "$@" ;;
  env-overrides)   env_overrides "$@" ;;
  tag-url)         tag_url "$@" ;;
  comment-body)    comment_body "$@" ;;
  comment-id)      comment_id ;;
  comment)         post_comment "$@" ;;
  is-not-found)    is_not_found "$@" ;;
  cleanup)         cleanup "$@" ;;
  *) die "usage: pr_preview.sh firebase-config|env-overrides|tag-url|comment-body|comment-id|comment|is-not-found|cleanup ..." ;;
esac
