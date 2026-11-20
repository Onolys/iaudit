#!/usr/bin/env python3
"""Identity Platform settings the Terraform google provider cannot express (PRD R4), plus extra authorised domains.

Usage (ADC, quota project `onolys`):
  python3 infra/scripts/identity-config.py                      # ensure password policy (min 8) + enumeration protection
  python3 infra/scripts/identity-config.py --domains-only --add-domain HOST ...  # union HOST(s) into authorised domains

Idempotent: PATCHes only when the live config differs; domains are only ever added, never removed.
Terraform runs it (with the base domain list) when this file or that list changes
(terraform_data.identity_policy). Preview channel hosts are added by the SP00 preview workflow with
--domains-only: the wildcard `onolys-app-staging--pr-*.web.app` is rejected by the API
(INVALID_AUTHORIZED_DOMAIN), see docs/reference/testing.md "Preview auth domains".
"""
import argparse
import json
import sys
import urllib.request

PROJECT = "onolys"
BASE = f"https://identitytoolkit.googleapis.com/admin/v2/projects/{PROJECT}/config"

POLICY = {
    "passwordPolicyEnforcementState": "ENFORCE",
    "passwordPolicyVersions": [{"customStrengthOptions": {"minPasswordLength": 8}}],
}
PRIVACY = {"enableImprovedEmailPrivacy": True}


def _policy_ok(cur):
    vers = (cur or {}).get("passwordPolicyVersions") or []
    return (
        (cur or {}).get("passwordPolicyEnforcementState") == "ENFORCE"
        and any(v.get("customStrengthOptions", {}).get("minPasswordLength") == 8 for v in vers)
    )


def ensure(client):
    cfg = client.get()
    body = {}
    if not _policy_ok(cfg.get("passwordPolicyConfig")):
        body["passwordPolicyConfig"] = POLICY
    if not (cfg.get("emailPrivacyConfig") or {}).get("enableImprovedEmailPrivacy"):
        body["emailPrivacyConfig"] = PRIVACY
    if body:
        client.patch(",".join(body), body)
        print("patched: " + ", ".join(body))
    else:
        print("already set")


def add_domains(client, hosts):
    cur = client.get().get("authorizedDomains", [])
    new = [h for h in hosts if h not in cur]
    if not new:
        print("domains already present")
        return
    client.patch("authorizedDomains", {"authorizedDomains": cur + new})
    print("added: " + ", ".join(new))


class Client:
    def __init__(self):
        import google.auth
        import google.auth.transport.requests as tr

        self.creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        self.tr = tr.Request()

    def _call(self, method, url, body=None):
        self.creds.refresh(self.tr)
        req = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.creds.token}",
                "x-goog-user-project": PROJECT,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            sys.exit(f"{method} {url} -> {e.code}: {e.read().decode()[:500]}")

    def get(self):
        return self._call("GET", BASE)

    def patch(self, mask, body):
        self._call("PATCH", f"{BASE}?updateMask={mask}", body)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-domain", action="append", default=[], metavar="HOST")
    ap.add_argument("--domains-only", action="store_true", help="skip the policy check (fast path for CI preview deploys)")
    args = ap.parse_args(argv)
    c = Client()
    if args.domains_only:
        add_domains(c, args.add_domain)
        return
    ensure(c)
    if args.add_domain:
        add_domains(c, args.add_domain)


if __name__ == "__main__":
    main()
