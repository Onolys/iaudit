#!/usr/bin/env python3
"""Live env checks, staging (default) or prod (PRD R8 resolved checks, R10, AC3/AC4/AC6). ADC auth, no gcloud. Prints results, exit 1 on any failure.

  python3 infra/scripts/check-staging.py [--env prod]  # anon invoker checks, worker env refs, IAM isolation both ways, WIF binding
  python3 infra/scripts/check-staging.py --egress   # also: one-off Cloud Run job hits api.anthropic.com, then is deleted

Note: no x-goog-user-project header on any call (keeps it safe for CloudBilling-style APIs); every API used here
works without it. No secret values are read or printed.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT, REGION = "onolys", "us-central1"
ENV = "staging"  # default; main() takes --env


def sas_for(env):
    return [f"serviceAccount:{n}-{env}@{PROJECT}.iam.gserviceaccount.com" for n in ("api", "worker", "tasks-invoker", "deployer")]


def other_env(env):
    return "prod" if env == "staging" else "staging"


STAGING_SAS = sas_for("staging")
# Unconditioned project-level roles allowed for env SAs (shared, non-environment data).
UNCONDITIONED_OK = {"roles/speech.client", "roles/serviceusage.serviceUsageConsumer"}


def env_resources(env):
    """Per-env resources that no other-env SA may be bound on. Provider-key secrets are shared by design (PRD D12)."""
    return {
        "bucket": f"{PROJECT}-audio-{env}",
        "secret": f"uid-hmac-key-{env}",
        "queue": f"steps-{env}",
        "service-api": f"onolys-api-{env}",
        "service-worker": f"onolys-worker-{env}",
    }


# ---- pure assertions (unit-tested) ----
def anon_api_ok(code):
    return code in (200, 404)


def anon_worker_denied(code):
    return code in (401, 403)


def worker_env_problems(env):
    out = []
    byname = {e["name"]: e for e in env}
    ref = byname.get("ANTHROPIC_API_KEY")
    if ref is None:
        out.append("ANTHROPIC_API_KEY missing")
    elif "valueSource" not in ref or "value" in ref:
        out.append("ANTHROPIC_API_KEY is not a pure secret ref")
    hm = byname.get("UID_HMAC_KEY")
    if hm is not None and ("valueSource" not in hm or "value" in hm):
        out.append("UID_HMAC_KEY is not a pure secret ref")
    for n, e in byname.items():
        if n not in ("ANTHROPIC_API_KEY", "UID_HMAC_KEY") and (n.endswith("_API_KEY") or n.startswith("STT_") or "valueSource" in e):
            out.append(f"unexpected provider/secret env: {n}")
    return out


def _cond_scoped(cond, env):
    staging_marks = ("databases/staging" in cond or "-staging" in cond or "releases/cloud.firestore/staging" in cond)
    if env == "staging":
        return staging_marks and "databases/(default)" not in cond
    prod_marks = "databases/(default)" in cond or "sites/onolys-app" in cond or "releases/cloud.firestore\"" in cond
    return prod_marks and not staging_marks


def project_iam_problems(policy, sas, env="staging"):
    out = []
    for b in policy.get("bindings", []):
        who = [m for m in b["members"] if m in sas]
        if not who:
            continue
        cond = (b.get("condition") or {}).get("expression", "")
        if cond:
            if not _cond_scoped(cond, env):
                out.append(f"{b['role']} for {who}: condition not {env}-scoped: {cond}")
        elif b["role"] not in UNCONDITIONED_OK:
            out.append(f"{b['role']} for {who}: unconditioned project-level grant")
    return out


def resource_policy_problems(resource, policy, sas, env="staging"):
    """`sas` are env's SAs; any binding on another env's resource is a problem."""
    if f"-{env}" in resource:
        return []
    return [f"{resource}: {r} grants {m}" for b in policy.get("bindings", []) for m in b["members"] if m in sas for r in [b["role"]]]


def wif_binding_problems(env, policy):
    """deployer-prod: only the `production` GitHub environment principal. deployer-staging: repo-wide, never the production one."""
    members = [m for b in policy.get("bindings", []) if b["role"] == "roles/iam.workloadIdentityUser" for m in b["members"]]
    if env == "prod":
        if not members:
            return ["deployer-prod has no workloadIdentityUser binding"]
        return [f"deployer-prod trusts {m}" for m in members if not m.endswith("/attribute.environment/production")]
    return [f"deployer-staging trusts {m}" for m in members if m.endswith("/attribute.environment/production")]


# ---- live ----
def _token():
    c = json.load(open(Path.home() / ".config/gcloud/application_default_credentials.json"))
    d = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", d))["access_token"]


def call(method, url, tok=None, body=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(url, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, (json.loads(r.read() or b"{}") if r.headers.get("content-type", "").startswith("application/json") else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {}


def run_egress(tok):
    base = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/jobs"
    name = "egress-check-tmp"
    code_py = ("import urllib.request,urllib.error,sys\n"
               "try:\n r=urllib.request.urlopen('https://api.anthropic.com/v1/models',timeout=20);print('HTTP',r.status)\n"
               "except urllib.error.HTTPError as e:\n print('HTTP',e.code)\n"
               "except Exception as e:\n print('FAIL',e);sys.exit(1)\n")
    job = {"template": {"template": {"maxRetries": 0, "timeout": "60s",
           "serviceAccount": f"worker-{ENV}@{PROJECT}.iam.gserviceaccount.com",
           "containers": [{"image": "mirror.gcr.io/library/python:3.12-slim", "command": ["python", "-c"], "args": [code_py]}]}}}
    ok = False
    try:
        s, r = call("POST", f"{base}?jobId={name}", tok, job)
        print("create job:", s, r.get("error", {}).get("message", ""))
        if s >= 300:
            return False
        for _ in range(30):
            time.sleep(4)
            if call("GET", f"{base}/{name}", tok)[1].get("terminalCondition", {}).get("state") == "CONDITION_SUCCEEDED":
                break
        s, r = call("POST", f"{base}/{name}:run", tok, {})
        print("run job:", s, r.get("error", {}).get("message", ""))
        if s >= 300:
            return False
        for _ in range(45):
            time.sleep(4)
            s, r = call("GET", f"{base}/{name}/executions", tok)
            ex = (r.get("executions") or [{}])[0]
            if ex.get("completionTime"):
                ok = ex.get("succeededCount", 0) == 1
                print(f"execution: succeeded={ex.get('succeededCount', 0)} failed={ex.get('failedCount', 0)} (job exits 0 on any HTTP reply from api.anthropic.com, 1 on connect failure)")
                break
        return ok
    finally:
        s, _ = call("DELETE", f"{base}/{name}", tok)
        print("delete job:", s)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", choices=["staging", "prod"], default="staging")
    ap.add_argument("--egress", action="store_true")
    a = ap.parse_args(argv)
    global ENV
    ENV = env = a.env
    tok = _token()
    fails = []

    def rec(label, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + label + (f": {detail}" if detail else ""))
        if not ok:
            fails.append(label)

    run = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/services"
    uris = {}
    for svc in ("api", "worker"):
        s, d = call("GET", f"{run}/onolys-{svc}-{env}", tok)
        uris[svc] = d["uri"]
        if svc == "worker":
            rec("worker env refs", not worker_env_problems(d["template"]["containers"][0].get("env", [])),
                "; ".join(worker_env_problems(d["template"]["containers"][0].get("env", []))) or "ANTHROPIC_API_KEY (+UID_HMAC_KEY) secret refs only")
    s, _ = call("GET", uris["api"] + "/")
    rec("anonymous api", anon_api_ok(s), f"HTTP {s}")
    s, _ = call("GET", uris["worker"] + "/")
    rec("anonymous worker", anon_worker_denied(s), f"HTTP {s}")
    for _ in range(3):  # CRM occasionally answers non-200 without a quota project; retry
        s, pol = call("POST", f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}:getIamPolicy", tok,
                      {"options": {"requestedPolicyVersion": 3}})
        if s == 200:
            break
        time.sleep(2)
    for e in (env, other_env(env)):
        probs = project_iam_problems(pol, sas_for(e), env=e)
        rec(f"project IAM {e}-scoped ({e} SAs)", s == 200 and not probs,
            "; ".join(probs) if probs else (f"HTTP {s}" if s != 200 else f"all {e} SA grants conditioned to {e} or on the allowlist"))
    # Cross-env resource policies: no other-env SA on this env's resources, and no this-env SA on the other env's.
    # Both directions are checked so either env's run proves the pair.
    urls = {
        "bucket": lambda n: f"https://storage.googleapis.com/storage/v1/b/{n}/iam",
        "secret": lambda n: f"https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets/{n}:getIamPolicy",
        "queue": lambda n: f"https://cloudtasks.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/queues/{n}:getIamPolicy",
        "service-api": lambda n: f"{run}/{n}:getIamPolicy",
        "service-worker": lambda n: f"{run}/{n}:getIamPolicy",
    }
    for owner in (env, other_env(env)):
        for kind, name in env_resources(owner).items():
            url = urls[kind](name)
            s, pol = call("POST", url, tok, {}) if kind == "queue" else call("GET", url, tok)
            if s == 404:
                print(f"SKIP {kind} {name} does not exist (HTTP 404)")
                continue
            probs = resource_policy_problems(name, pol, sas_for(other_env(owner)), env=other_env(owner))
            rec(f"{kind} {name}: no {other_env(owner)} SA bound", s == 200 and not probs, "; ".join(probs) or f"HTTP {s}")
    # Deployer impersonation bindings (trust conditions; the GitHub-side test run is SP06 T13)
    s, pol = call("POST", f"https://iam.googleapis.com/v1/projects/{PROJECT}/serviceAccounts/deployer-{env}@{PROJECT}.iam.gserviceaccount.com:getIamPolicy", tok, {})
    probs = wif_binding_problems(env, pol)
    rec(f"deployer-{env} WIF binding", s == 200 and not probs, "; ".join(probs) or f"HTTP {s}")
    s, pol = call("GET", f"{run}/onolys-worker-{env}:getIamPolicy", tok)
    members = [m for b in pol.get("bindings", []) for m in b["members"]]
    rec("worker invoker not public", "allUsers" not in members and "allAuthenticatedUsers" not in members, ", ".join(members))
    s, pol = call("GET", f"{run}/onolys-api-{env}:getIamPolicy", tok)
    rec("api allUsers invoker binding", any(m == "allUsers" for b in pol.get("bindings", []) for m in b["members"]), "org policy did not block")
    if a.egress:
        rec("egress to api.anthropic.com", run_egress(tok))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
