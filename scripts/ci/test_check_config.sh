#!/usr/bin/env bash
# Tests for check_config.sh: fails when a required config file is missing, passes when present.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
mk() { mkdir -p "$T/docs/contracts"; for c in audit-request audit-response error-response; do echo "{}" > "$T/docs/contracts/$c.schema.json"; done; for e in staging prod; do mkdir -p "$T/config/$e"; for f in routes stt_providers; do echo "x: 1" > "$T/config/$e/$f.yaml"; done; done; }
expect() { # <want rc> <label> [args...]
  local want="$1" label="$2"; shift 2
  ROOT="$T" bash "$HERE/check_config.sh" "$@" >/dev/null 2>&1; local rc=$?
  if { [[ "$want" == 0 && $rc -eq 0 ]] || [[ "$want" == nz && $rc -ne 0 ]]; }; then echo "ok   $label"; else echo "FAIL $label (rc=$rc)"; fail=1; fi
}
mk
expect 0  "all files present"
rm "$T/config/prod/stt_providers.yaml"
expect nz "missing prod/stt_providers.yaml"
mk; rm "$T/config/staging/routes.yaml"
expect nz "missing staging/routes.yaml"
mk; : > "$T/config/staging/routes.yaml"
expect nz "empty file"
mk
# image mode: fake docker that lists files; one missing
mkdir -p "$T/bin"
cat > "$T/bin/docker" <<'D'
#!/usr/bin/env bash
# docker run --rm --entrypoint test img -s <path>
path="${@: -1}"
[[ "$path" == */prod/routes.yaml && -n "${MISSING_IN_IMAGE:-}" ]] && exit 1
[[ "$path" == /app/contracts/* && -n "${MISSING_CONTRACT_IN_IMAGE:-}" ]] && exit 1
exit 0
D
chmod +x "$T/bin/docker"
PATH="$T/bin:$PATH" expect 0 "image mode, all present" --image fake:img
MISSING_IN_IMAGE=1 PATH="$T/bin:$PATH" expect nz "image mode, one missing" --image fake:img
MISSING_CONTRACT_IN_IMAGE=1 PATH="$T/bin:$PATH" expect nz "image mode, contracts missing" --image fake:img
mk; rm "$T/docs/contracts/audit-response.schema.json"
expect nz "missing source contract"
exit $fail
