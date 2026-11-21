#!/usr/bin/env bash
# Creates the versioned, private Terraform state bucket (idempotent) using curl + ADC. No gcloud.
set -euo pipefail
PROJECT="${PROJECT:-onolys}"
BUCKET="${BUCKET:-onolys-tfstate}"
LOCATION="${LOCATION:-us-central1}"
ADC="${GOOGLE_APPLICATION_CREDENTIALS:-$HOME/.config/gcloud/application_default_credentials.json}"

token="$(python3 -I - "$ADC" <<'PY'
import json, sys, urllib.parse, urllib.request
c = json.load(open(sys.argv[1]))
d = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                            "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
print(json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", d))["access_token"])
PY
)"
auth=(-H "Authorization: Bearer $token" -H "x-goog-user-project: $PROJECT")
api="https://storage.googleapis.com/storage/v1/b"

code="$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" "$api/$BUCKET")"
if [ "$code" = "404" ]; then
  curl -fsS "${auth[@]}" -H 'Content-Type: application/json' -X POST "$api?project=$PROJECT" -d "{
    \"name\": \"$BUCKET\", \"location\": \"$LOCATION\",
    \"versioning\": {\"enabled\": true},
    \"iamConfiguration\": {\"uniformBucketLevelAccess\": {\"enabled\": true}, \"publicAccessPrevention\": \"enforced\"}}" >/dev/null
  echo "created gs://$BUCKET"
elif [ "$code" != "200" ]; then
  echo "unexpected HTTP $code checking gs://$BUCKET" >&2; exit 1
else
  # ensure settings even if it already existed
  curl -fsS "${auth[@]}" -H 'Content-Type: application/json' -X PATCH "$api/$BUCKET" -d '{
    "versioning": {"enabled": true},
    "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": true}, "publicAccessPrevention": "enforced"}}' >/dev/null
  echo "gs://$BUCKET already exists (settings verified)"
fi
