#!/usr/bin/env bash
# Guard: firebase-tools resolves .firebaserc next to the --config file, so every app dir that is deployed with
# `--config <dir>/firebase.json --only hosting:<target>` must carry its own .firebaserc mapping each target in
# its firebase.json to a site. Run from anywhere.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }

for dir in web frontend; do
  fb="$ROOT/$dir/firebase.json"; rc="$ROOT/$dir/.firebaserc"
  [[ -f "$rc" ]] && ok "$dir/.firebaserc exists" || { bad "$dir/.firebaserc exists"; continue; }
  python3 - "$fb" "$rc" <<'PY' && ok "$dir: every hosting target in firebase.json maps to a site" || bad "$dir: every hosting target in firebase.json maps to a site"
import json, sys
fb, rc = (json.load(open(p)) for p in sys.argv[1:3])
rcj = rc
project = rcj["projects"]["default"]
mapped = rcj.get("targets", {}).get(project, {}).get("hosting", {})
targets = [h["target"] for h in fb["hosting"]]
missing = [t for t in targets if not mapped.get(t)]
if missing:
    print("unmapped targets:", missing, file=sys.stderr); sys.exit(1)
PY
done
exit $fail
