#!/usr/bin/env bash
# Helpers for pr-preview.yml / pr-preview-cleanup.yml (SP00 R3). Pure functions, no cloud calls except `cleanup`.
#   pr_preview.sh firebase-config <api origin> <src firebase.json> <out>   Hosting config: target app-staging only, no /v1/** rewrite
#                                                                          (the web build calls the tag URL directly), API origin added to CSP connect-src
#   pr_preview.sh env-overrides <adapters> <sha> <cors origin>     value for `gcloud run deploy --update-env-vars` (custom `^|^` delimiter)
#   pr_preview.sh tag-url <service url> <pr>                       https://pr-<pr>---<service host>
#   pr_preview.sh channel-url <channel.json> <site>                url of <site> in `firebase hosting:channel:deploy --json` output (.result is keyed by target, so select by .site); exit 1 if absent
#   pr_preview.sh comment-body <pr> <url> <sha> <fake|real>        marker PR comment body
#   pr_preview.sh comment-id                                        stdin: JSON list of PR comments -> id of the first marker comment (or empty)
#   pr_preview.sh comment <pr> <url> <sha> <mode>                   create-or-update the ONE marker comment (needs gh, GITHUB_REPOSITORY, GH_TOKEN)
#   pr_preview.sh is-not-found <text>                               exit 0 when text looks like a not-found error
#   pr_preview.sh cleanup <pr>                                      remove tag pr-<pr> + delete its revisions on the staging API service, delete the Hosting channel (not-found ignored). The newest revision cannot be deleted by Cloud Run: logged `left for sweep`, channel step always runs
#   pr_preview.sh restore-template [pr]                             put the staging API service TEMPLATE back to the config of the revision that serves traffic (a preview deploy rewrites it); no-op when it already matches; traffic/tags untouched
#   pr_preview.sh sweep                                             delete untagged, 0%-traffic, non-latest ^<service>-pr-<N>- revisions (non-preview and tagged revisions untouched)
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

channel_url() {
  local file="${1:-}" site="${2:-}" url
  [[ -f "$file" && -n "$site" ]] || die "usage: channel-url <channel.json> <site>"
  url="$(jq -r --arg s "$site" '[.result[]? | select(.site == $s) | .url][0] // empty' "$file")"
  [[ -n "$url" ]] || die "no channel url for site '$site' in $file"
  printf '%s\n' "$url"
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

is_latest_revision_error() {
  printf '%s' "${1:-}" | grep -Eiq 'latest created Revision.*cannot be directly deleted'
}

# Run a delete command. Returns 0 on success, not-found (ignored) or, with LATEST_OK=1, the Cloud Run "latest created
# Revision cannot be directly deleted" rule (logged as `left for sweep: <rev>`); returns 1 on any other error. Never exits.
delete_ignoring_not_found() {
  local what="$1"; shift
  local out rc=0
  out="$("$@" 2>&1)" || rc=$?
  printf '%s\n' "$out"
  [[ $rc -eq 0 ]] && return 0
  if is_not_found "$out"; then echo "$what: already gone (ignored)"; return 0; fi
  if [[ "${LATEST_OK:-}" == 1 ]] && is_latest_revision_error "$out"; then echo "left for sweep: ${what#Cloud Run revision }"; return 0; fi
  echo "pr_preview.sh: $what: delete failed" >&2; return 1
}

# Delete orphan preview revisions of the staging API service: name ^<service>-pr-<digits>-, no traffic tag, 0% traffic,
# not the latest created revision (Cloud Run refuses to delete that one). Never touches non-preview or tagged (open PR) revisions.
sweep() {
  local svc latest protected names rev rc=0
  svc="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format json)" || { echo "sweep: describe failed" >&2; return 1; }
  latest="$(printf '%s' "$svc" | jq -er '.status.latestCreatedRevisionName // empty')" || { echo "sweep: cannot read latest revision; not deleting anything" >&2; return 1; }
  protected="$(printf '%s' "$svc" | jq -r '.status.traffic[]? | select((.tag // "") != "" or (.percent // 0) > 0) | .revisionName // empty')" || { echo "sweep: cannot read traffic" >&2; return 1; }
  names="$(gcloud run revisions list --service "$SERVICE" --region "$REGION" --project "$PROJECT" \
    --filter "metadata.name~^${SERVICE}-pr-[0-9]+-" --format 'value(metadata.name)')" || { echo "sweep: listing revisions failed" >&2; return 1; }
  for rev in $names; do
    [[ "$rev" =~ ^${SERVICE}-pr-[0-9]+- ]] || continue
    [[ "$rev" == "$latest" ]] && { echo "sweep: keeping latest $rev"; continue; }
    if printf '%s\n' "$protected" | grep -qxF "$rev"; then echo "sweep: keeping $rev (tagged or serving traffic)"; continue; fi
    LATEST_OK=1 delete_ignoring_not_found "Cloud Run revision $rev" \
      gcloud run revisions delete "$rev" --region "$REGION" --project "$PROJECT" --quiet || rc=1
  done
  return $rc
}

# --- restore-template -------------------------------------------------------------------------------------------------
# `gcloud run deploy --no-traffic --tag` always rewrites the service template, so after a preview the template (env
# ADAPTERS=stub, SERVICE_MODE=combined, GIT_SHA, CORS_ORIGINS, cpu_idle=false) differs from the revision that serves traffic:
# Terraform sees drift and any later template-based revision would start in preview mode. restore-template puts the template back
# to the serving revision's config with a Cloud Run v2 PATCH (updateMask=template). Only `template` is in the mask, so traffic
# (pinned to revisions by name) and tags are untouched; the restore creates one more 0%-traffic revision, named
# <service>-pr-<N>-tpl-<epoch> so cleanup / sweep delete it like any preview revision. The etag in the body makes a concurrent
# staging deploy fail the PATCH (409) instead of being overwritten; the whole read-compare-patch is then retried.
# TPL_KEYS: RevisionTemplate fields (a Revision has the same ones plus output-only fields, which are dropped).
TPL_KEYS='["labels","annotations","scaling","vpcAccess","timeout","serviceAccount","containers","volumes","executionEnvironment","encryptionKey","maxInstanceRequestConcurrency","serviceMesh","encryptionKeyRevocationAction","encryptionKeyShutdownDuration","sessionAffinity","healthCheckDisabled","nodeSelector","gpuZonalRedundancyDisabled"]'
# Compare form: image and container name are excluded (the service stores the image as submitted, the revision the resolved
# digest, so they differ on a clean service; a preview always changes env/cpu, which this detects).
# System-managed label/annotation keys are stripped (they are rejected on write or never match the service template); empty maps dropped.
TPL_SYS='^(serving\\.knative\\.dev|cloud\\.googleapis\\.com|run\\.googleapis\\.com|autoscaling\\.knative\\.dev|client\\.knative\\.dev)/'
TPL_PICK="with_entries(select(.key as \$k | ${TPL_KEYS} | index(\$k))) | (.labels, .annotations) |= (if . == null then null else with_entries(select(.key | test(\"${TPL_SYS}\") | not)) end) | with_entries(select(.value != null and .value != {}))"
TPL_CMP="${TPL_PICK} | if .containers then .containers |= map(del(.image, .name)) else . end"
RUN_BASE="projects/${PROJECT}/locations/${REGION}"

run_api() {  # run_api <METHOD> <path under https://run.googleapis.com/v2/> [json body] -> body; non-zero on HTTP/transport error
  local method="$1" path="$2" body="${3:-}" token
  token="$(gcloud auth print-access-token)" || return 1
  # The bearer header goes through stdin (-H @-), not argv (visible in the process list).
  if [[ -n "$body" ]]; then
    printf 'Authorization: Bearer %s\n' "$token" | curl -sS --fail-with-body -X "$method" -H @- -H 'Content-Type: application/json' -d "$body" "https://run.googleapis.com/v2/$path"
  else
    printf 'Authorization: Bearer %s\n' "$token" | curl -sS --fail-with-body -X "$method" -H @- "https://run.googleapis.com/v2/$path"
  fi
}

# rc 0 = matches / restored, 1 = hard error, 3 = etag conflict (caller retries)
restore_template_once() {
  local svc serving tplrev rev want have body resp gen obs state i
  svc="$(run_api GET "$RUN_BASE/services/$SERVICE")" || { echo "restore-template: cannot read service" >&2; return 1; }
  serving="$(printf '%s' "$svc" | jq -er '[.traffic[]? | select(.type == "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION" and (.percent // 0) > 0)] | sort_by(.percent) | last | .revision // empty')" \
    || { echo "restore-template: no revision serves traffic; template left alone" >&2; return 1; }
  # Only ever undo a PREVIEW deploy. A staging deploy sets the template to the new release while traffic is still on the old revision
  # (30-60 s); restoring then would roll the template (and deploy-prod's blank-sha GIT_SHA read) back. So: template revision must be a
  # preview revision (<service>-pr-<N>-..., not one of our own -tpl- restores) and the service must not be reconciling.
  tplrev="$(printf '%s' "$svc" | jq -r '.template.revision // empty')"
  if [[ ! "$tplrev" =~ ^${SERVICE}-pr-[0-9]+- || "$tplrev" == *-tpl-* ]]; then
    echo "restore-template: template revision '${tplrev:-none}' is not a preview revision; left alone"; return 0
  fi
  if [[ "$(printf '%s' "$svc" | jq -r '.reconciling // false')" == true ]]; then
    echo "restore-template: service is reconciling (another update in flight); left alone"; return 0
  fi
  rev="$(run_api GET "$RUN_BASE/services/$SERVICE/revisions/$serving")" || { echo "restore-template: cannot read revision $serving" >&2; return 1; }
  want="$(printf '%s' "$rev" | jq -S "$TPL_CMP")" && have="$(printf '%s' "$svc" | jq -S ".template | $TPL_CMP")" || { echo "restore-template: unreadable JSON" >&2; return 1; }
  [[ -n "$want" && "$want" != null ]] || { echo "restore-template: empty revision template" >&2; return 1; }
  if [[ "$want" == "$have" ]]; then echo "restore-template: template already matches serving revision $serving"; return 0; fi
  body="$(jq -nc --argjson rev "$rev" --arg etag "$(printf '%s' "$svc" | jq -r '.etag // empty')" --arg n "${SERVICE}-pr-${TPL_PR:-0}-tpl-$(date +%s)" \
    "{etag: \$etag, template: ((\$rev | ${TPL_PICK}) + {revision: \$n})}")" || return 1
  if ! resp="$(run_api PATCH "$RUN_BASE/services/$SERVICE?updateMask=template" "$body" 2>&1)"; then
    printf '%s\n' "$resp" >&2
    printf '%s' "$resp" | grep -Eiq 'ABORTED|etag|409|modified|conflict' && return 3
    echo "restore-template: PATCH failed" >&2; return 1
  fi
  # Wait on the SERVICE, not the long-running operation (the deployer SA may not read operations): the PATCH response carries the
  # service generation this update produced; done = Ready and observedGeneration >= that generation (a later one = a newer update).
  gen="$(printf '%s' "$resp" | jq -r '.metadata.generation // empty')"
  [[ "$gen" =~ ^[0-9]+$ ]] || gen="$(( $(printf '%s' "$svc" | jq -r '.generation // 0') + 1 ))"
  for i in $(seq 1 "${RESTORE_POLLS:-60}"); do
    resp="$(run_api GET "$RUN_BASE/services/$SERVICE")" || { echo "restore-template: cannot poll service" >&2; return 1; }
    state="$(printf '%s' "$resp" | jq -r '.terminalCondition.state // empty')"
    obs="$(printf '%s' "$resp" | jq -r '.observedGeneration // 0')"
    if [[ "$obs" =~ ^[0-9]+$ && "$obs" -ge "$gen" ]]; then
      case "$state" in
        CONDITION_SUCCEEDED) echo "restore-template: template restored from serving revision $serving (generation $obs)"; return 0 ;;
        CONDITION_FAILED) echo "restore-template: service update failed: $(printf '%s' "$resp" | jq -c '.terminalCondition')" >&2; return 1 ;;
      esac
    fi
    sleep "${RESTORE_POLL_SLEEP:-5}"
  done
  echo "restore-template: service did not reach generation $gen (Ready) in time" >&2; return 1
}

restore_template() {
  local attempt rc
  [[ -z "${1:-}" ]] || { need_pr "$1"; TPL_PR="$1"; }
  for attempt in 1 2 3; do
    rc=0; restore_template_once || rc=$?
    [[ $rc -ne 3 ]] && return $rc
    echo "restore-template: concurrent update; retrying ($attempt)" >&2; sleep "${RESTORE_RETRY_SLEEP:-10}"
  done
  return 1
}

cleanup() {
  local pr="${1:-}"; need_pr "$pr"
  local fail=0 names rev
  delete_ignoring_not_found "Cloud Run tag pr-$pr" \
    gcloud run services update-traffic "$SERVICE" --remove-tags "pr-$pr" --region "$REGION" --project "$PROJECT" --quiet || fail=1
  # Safety net: a preview deploy cancelled before its own restore (cancel-in-progress) would leave the preview template. Idempotent
  # (only acts on a preview-named template). When it acts, its own <service>-pr-<N>-tpl-<epoch> revision becomes the newest revision,
  # which Cloud Run will not delete: it is logged `left for sweep` below and removed by the next sweep; the older preview revisions can go.
  restore_template "$pr" || { echo "pr_preview.sh: restore-template failed" >&2; fail=1; }
  # Tag first: a revision that still carries a tag (or traffic) cannot be deleted. Revision names: <service>-pr-<N>-<sha7>-<run>-<attempt>.
  # Cloud Run never deletes the newest revision of a service; that case is left for `sweep`. Whatever happens above, the channel step still runs.
  if names="$(gcloud run revisions list --service "$SERVICE" --region "$REGION" --project "$PROJECT" \
    --filter "metadata.name~^${SERVICE}-pr-${pr}-" --format 'value(metadata.name)')"; then
    for rev in $names; do
      LATEST_OK=1 delete_ignoring_not_found "Cloud Run revision $rev" \
        gcloud run revisions delete "$rev" --region "$REGION" --project "$PROJECT" --quiet || fail=1
    done
  else
    echo "pr_preview.sh: listing revisions failed" >&2; fail=1
  fi
  delete_ignoring_not_found "Hosting channel pr-$pr" \
    npx --yes "firebase-tools@${FIREBASE_TOOLS_VERSION}" hosting:channel:delete "pr-$pr" --site "$SITE" --project "$PROJECT" --force --non-interactive || fail=1
  sweep || echo "warning: orphan sweep failed (non-fatal)" >&2
  return $fail
}

cmd="${1:-}"; [[ $# -gt 0 ]] && shift
case "$cmd" in
  firebase-config) firebase_config "$@" ;;
  env-overrides)   env_overrides "$@" ;;
  tag-url)         tag_url "$@" ;;
  channel-url)     channel_url "$@" ;;
  comment-body)    comment_body "$@" ;;
  comment-id)      comment_id ;;
  comment)         post_comment "$@" ;;
  is-not-found)    is_not_found "$@" ;;
  cleanup)         cleanup "$@" ;;
  restore-template) restore_template "$@" ;;
  sweep)           sweep ;;
  *) die "usage: pr_preview.sh firebase-config|env-overrides|tag-url|comment-body|comment-id|comment|is-not-found|cleanup|restore-template|sweep ..." ;;
esac
