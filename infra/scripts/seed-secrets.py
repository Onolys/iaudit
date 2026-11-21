#!/usr/bin/env python3
"""Write secret VALUES into Secret Manager shells created by Terraform (PRD D9: values never enter state).

Usage (staging; keys from the environment, never from argv or files in the repo):
  set -a; . ~/.config/onolys/keys.env; set +a
  python3 infra/scripts/seed-secrets.py --env staging
  # extra provider keys: --map GEMINI_API_KEY=gemini-api-key   (env var name = BASE secret id; written to <base>-{env})
  # admin allowlist:     ADMIN_ALLOWED_EMAILS="a@x.com,b@y.com" ... --admin

Provider keys are per environment: base id `anthropic-api-key` is written to `anthropic-api-key-{env}`.
Idempotent: a new secret version is added only when (a) the secret has no version yet, or
(b) the supplied value differs from the latest version. Otherwise nothing is written.
Special case: `uid-hmac-key-{env}` is random and generated only when it has no version
(never rotated by re-running). A provider key whose env var is unset keeps its existing
version; if it has none, the run fails (exit 1). Values are never printed.
Auth: Application Default Credentials (google-auth), quota project `onolys`.
"""
import argparse
import base64
import hmac
import os
import secrets
import sys

DEFAULT_MAP = {"ANTHROPIC_API_KEY": "anthropic-api-key"}


class Report:
    def __init__(self):
        self.lines = []
        self.ok = True

    def add(self, sid, status, fail=False):
        self.lines.append(f"{sid}: {status}")
        if fail:
            self.ok = False


def _put(client, rep, sid, value: bytes):
    cur = client.latest_value(sid)
    if cur is not None and hmac.compare_digest(cur, value):
        rep.add(sid, "unchanged")
    else:
        client.add_version(sid, value)
        rep.add(sid, "created" if cur is None else "new version")


def seed(client, *, env, provider_maps, environ, admin=False):
    rep = Report()
    hmac_id = f"uid-hmac-key-{env}"
    if client.latest_value(hmac_id) is None:
        client.add_version(hmac_id, secrets.token_hex(32).encode())
        rep.add(hmac_id, "created (random)")
    else:
        rep.add(hmac_id, "unchanged")
    wanted = {name: f"{base}-{env}" for name, base in provider_maps.items()}  # per-env secret ids
    for name, sid in sorted(wanted.items()):
        val = environ.get(name)
        if val:
            _put(client, rep, sid, val.encode())
        elif client.latest_value(sid) is not None:
            rep.add(sid, f"unchanged ({name} not set)")
        else:
            rep.add(sid, f"MISSING: set {name}", fail=True)
    if admin:
        sid = f"admin-allowed-emails-{env}"
        val = environ.get("ADMIN_ALLOWED_EMAILS")
        if val:
            _put(client, rep, sid, val.encode())
        elif client.latest_value(sid) is None:
            rep.add(sid, "MISSING: set ADMIN_ALLOWED_EMAILS", fail=True)
        else:
            rep.add(sid, "unchanged (ADMIN_ALLOWED_EMAILS not set)")
    return rep


class SecretManager:
    def __init__(self, project):
        import google.auth
        import google.auth.transport.requests as gr
        import requests

        self._creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self._req = gr.Request()
        self._http = requests
        self.project = project

    def _call(self, method, path, **kw):
        if not self._creds.valid:
            self._creds.refresh(self._req)
        headers = {"Authorization": f"Bearer {self._creds.token}", "x-goog-user-project": self.project}
        return self._http.request(
            method, f"https://secretmanager.googleapis.com/v1/projects/{self.project}/secrets/{path}",
            headers=headers, timeout=30, **kw)

    def latest_value(self, sid):
        r = self._call("GET", f"{sid}/versions/latest:access")
        if r.status_code in (400, 404, 412):  # 404 is ambiguous: no version, or no secret at all
            if self._call("GET", sid).status_code == 404:
                sys.exit(f"{sid}: secret shell does not exist; run terraform apply first")
            return None
        r.raise_for_status()
        return base64.b64decode(r.json()["payload"]["data"])

    def add_version(self, sid, value):
        data = base64.b64encode(value).decode()
        self._call("POST", f"{sid}:addVersion", json={"payload": {"data": data}}).raise_for_status()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", required=True, choices=["staging", "prod"])
    ap.add_argument("--project", default="onolys")
    ap.add_argument("--map", action="append", default=[], metavar="ENVVAR=secret-id",
                    help="provider key (repeatable); default ANTHROPIC_API_KEY=anthropic-api-key (base id; --env suffix is added)")
    ap.add_argument("--admin", action="store_true", help="also seed admin-allowed-emails-{env} from ADMIN_ALLOWED_EMAILS")
    a = ap.parse_args(argv)
    maps = dict(m.split("=", 1) for m in a.map) if a.map else dict(DEFAULT_MAP)
    rep = seed(SecretManager(a.project), env=a.env, provider_maps=maps, environ=os.environ, admin=a.admin)
    print("\n".join(rep.lines))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
