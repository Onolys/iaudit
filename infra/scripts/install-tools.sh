#!/usr/bin/env bash
# Installs the pinned terraform binary to ~/.local/bin (idempotent). No gcloud needed.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
want="$(tr -d '[:space:]' < "$here/../.terraform-version")"
dest="${TF_INSTALL_DIR:-$HOME/.local/bin}"
have="$("$dest/terraform" version -json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["terraform_version"])' 2>/dev/null || true)"
if [ "$have" = "$want" ]; then
  echo "terraform $want already installed at $dest/terraform"
  exit 0
fi
case "$(uname -m)" in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
os="$(uname -s | tr '[:upper:]' '[:lower:]')"
zip="terraform_${want}_${os}_${arch}.zip"
base="https://releases.hashicorp.com/terraform/${want}"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/$zip" "$base/$zip"
curl -fsSL -o "$tmp/SHA256SUMS" "$base/terraform_${want}_SHA256SUMS"
(cd "$tmp" && grep " $zip\$" SHA256SUMS | sha256sum -c -)
python3 -I -c 'import sys,zipfile;zipfile.ZipFile(sys.argv[1]).extract("terraform",sys.argv[2])' "$tmp/$zip" "$tmp"
mkdir -p "$dest"
install -m 0755 "$tmp/terraform" "$dest/terraform"
echo "installed terraform $want to $dest/terraform"
