"""Tests for check-staging.py pure assertions (no network). Run: python3 -m pytest infra/scripts -q"""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("check_staging", pathlib.Path(__file__).with_name("check-staging.py"))
chk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chk)

SA = "serviceAccount:worker-staging@onolys.iam.gserviceaccount.com"


def test_anon_api_ok_and_worker_denied():
    assert chk.anon_api_ok(200) and chk.anon_api_ok(404)
    assert not chk.anon_api_ok(401) and not chk.anon_api_ok(403)
    assert chk.anon_worker_denied(401) and chk.anon_worker_denied(403)
    assert not chk.anon_worker_denied(200) and not chk.anon_worker_denied(404)


def test_worker_env_refs_only_anthropic():
    ok = [{"name": "ANTHROPIC_API_KEY", "valueSource": {"secretKeyRef": {"secret": "anthropic-api-key"}}}, {"name": "ENV", "value": "staging"}]
    assert chk.worker_env_problems(ok) == []
    plain = [{"name": "ANTHROPIC_API_KEY", "value": "sk-x"}]
    assert chk.worker_env_problems(plain)
    extra = ok + [{"name": "GEMINI_API_KEY", "valueSource": {"secretKeyRef": {"secret": "g"}}}, {"name": "STT_X", "value": "1"}]
    assert len(chk.worker_env_problems(extra)) == 2
    assert chk.worker_env_problems([{"name": "ENV", "value": "staging"}])  # ref missing


def test_iam_project_bindings():
    good = {"bindings": [
        {"role": "roles/datastore.user", "members": [SA], "condition": {"expression": 'resource.name == "projects/onolys/databases/staging"'}},
        {"role": "roles/speech.client", "members": [SA]},
    ]}
    assert chk.project_iam_problems(good, [SA]) == []
    bad = {"bindings": [{"role": "roles/datastore.user", "members": [SA]}]}
    assert chk.project_iam_problems(bad, [SA])
    prod = {"bindings": [{"role": "roles/datastore.user", "members": [SA], "condition": {"expression": 'resource.name == "projects/onolys/databases/(default)"'}}]}
    assert chk.project_iam_problems(prod, [SA])


def test_resource_policy_no_staging_sa_on_prod():
    pol = {"bindings": [{"role": "roles/storage.objectAdmin", "members": [SA]}]}
    assert chk.resource_policy_problems("onolys-audio-prod", pol, [SA])
    assert chk.resource_policy_problems("onolys-audio-staging", pol, [SA]) == []


# ---- prod / env-parametrised ----
PSA = "serviceAccount:api-prod@onolys.iam.gserviceaccount.com"


def test_sas_for_env():
    assert chk.sas_for("prod") == [f"serviceAccount:{n}-prod@onolys.iam.gserviceaccount.com" for n in ("api", "worker", "tasks-invoker", "deployer")]
    assert chk.sas_for("staging")[0].endswith("api-staging@onolys.iam.gserviceaccount.com") or "api-staging" in chk.sas_for("staging")[0]


def test_prod_project_iam_scoping():
    good = {"bindings": [
        {"role": "roles/datastore.user", "members": [PSA], "condition": {"expression": 'resource.name == "projects/onolys/databases/(default)"'}},
        {"role": "roles/firebasehosting.admin", "members": [PSA], "condition": {"expression": 'resource.name == "projects/onolys/sites/onolys-app" || resource.name.startsWith("projects/onolys/sites/onolys-app/")'}},
        {"role": "roles/firebaserules.admin", "members": [PSA], "condition": {"expression": 'resource.name.startsWith("projects/onolys/rulesets/") || resource.name == "projects/onolys/releases/cloud.firestore"'}},
        {"role": "roles/speech.client", "members": [PSA]},
    ]}
    assert chk.project_iam_problems(good, [PSA], env="prod") == []
    staging_db = {"bindings": [{"role": "roles/datastore.user", "members": [PSA], "condition": {"expression": 'resource.name == "projects/onolys/databases/staging"'}}]}
    assert chk.project_iam_problems(staging_db, [PSA], env="prod")
    uncond = {"bindings": [{"role": "roles/datastore.user", "members": [PSA]}]}
    assert chk.project_iam_problems(uncond, [PSA], env="prod")
    stg_site = {"bindings": [{"role": "roles/firebasehosting.admin", "members": [PSA], "condition": {"expression": 'resource.name.startsWith("projects/onolys/sites/onolys-app-staging")'}}]}
    assert chk.project_iam_problems(stg_site, [PSA], env="prod")


def test_resource_policy_cross_env():
    pol = {"bindings": [{"role": "roles/storage.objectAdmin", "members": [PSA]}]}
    assert chk.resource_policy_problems("onolys-audio-prod", pol, [PSA], env="prod") == []
    assert chk.resource_policy_problems("onolys-audio-staging", pol, [PSA], env="prod")
    assert chk.resource_policy_problems("onolys-audio-prod", {"bindings": [{"role": "r", "members": [SA]}]}, [SA], env="staging")


def test_other_env():
    assert chk.other_env("prod") == "staging" and chk.other_env("staging") == "prod"


def test_wif_binding_prod_only_production_env():
    pool = "projects/1/locations/global/workloadIdentityPools/github"
    prod_ok = {"bindings": [{"role": "roles/iam.workloadIdentityUser", "members": [f"principalSet://iam.googleapis.com/{pool}/attribute.environment/production"]}]}
    assert chk.wif_binding_problems("prod", prod_ok) == []
    repo_wide = {"bindings": [{"role": "roles/iam.workloadIdentityUser", "members": [f"principalSet://iam.googleapis.com/{pool}/attribute.repository/Onolys/onolys"]}]}
    assert chk.wif_binding_problems("prod", repo_wide)
    staging_env = {"bindings": [{"role": "roles/iam.workloadIdentityUser", "members": [f"principalSet://iam.googleapis.com/{pool}/attribute.environment/staging"]}]}
    assert chk.wif_binding_problems("prod", staging_env)
    assert chk.wif_binding_problems("prod", {"bindings": []})
    extra = {"bindings": [{"role": "roles/iam.workloadIdentityUser", "members": [f"principalSet://iam.googleapis.com/{pool}/attribute.environment/production", f"principalSet://iam.googleapis.com/{pool}/attribute.repository/Onolys/onolys"]}]}
    assert chk.wif_binding_problems("prod", extra)
    # staging deployer: repo-wide, must not include production environment principal
    assert chk.wif_binding_problems("staging", repo_wide) == []
    assert chk.wif_binding_problems("staging", prod_ok)
