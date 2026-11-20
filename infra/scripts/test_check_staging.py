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
