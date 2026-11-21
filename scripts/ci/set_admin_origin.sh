#!/usr/bin/env bash
# Replace the __ADMIN_BACKEND_ORIGIN__ placeholder in a Hosting config with the real admin-backend
# Cloud Run origin (SP07 R9). Usage: set_admin_origin.sh https://<service>.run.app <firebase.json>
# Fails on a malformed origin, a file without the placeholder, or any placeholder left over.
set -euo pipefail
origin="${1:-}"; file="${2:-}"
[[ "$origin" =~ ^https://[A-Za-z0-9.-]+$ ]] || { echo "origin must be https://host with no path: '$origin'" >&2; exit 1; }
[[ -f "$file" ]] || { echo "no such file: $file" >&2; exit 1; }
grep -q '__ADMIN_BACKEND_ORIGIN__' "$file" || { echo "placeholder not found in $file" >&2; exit 1; }
sed -i "s|__ADMIN_BACKEND_ORIGIN__|$origin|g" "$file"
if grep -q '__ADMIN_BACKEND_ORIGIN__' "$file"; then echo "placeholder still present in $file" >&2; exit 1; fi
echo "set admin origin $origin in $file"
