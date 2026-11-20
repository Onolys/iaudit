"""Tests for seed-secrets.py logic (fake client, no network). Run: python3 -m pytest infra/scripts -q"""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("seed_secrets", pathlib.Path(__file__).with_name("seed-secrets.py"))
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


class Fake:
    def __init__(self, existing=None):
        self.v = dict(existing or {})
        self.adds = []

    def latest_value(self, sid):
        return self.v.get(sid)

    def add_version(self, sid, value):
        self.v[sid] = value
        self.adds.append(sid)


def run(c, env, **kw):
    return seed.seed(c, env="staging", provider_maps={"ANTHROPIC_API_KEY": "anthropic-api-key"}, environ=env, **kw)


def test_creates_hmac_and_key_then_idempotent():
    c = Fake()
    r1 = run(c, {"ANTHROPIC_API_KEY": "sk-test-1"})
    assert r1.ok and sorted(c.adds) == ["anthropic-api-key", "uid-hmac-key-staging"]
    assert len(c.v["uid-hmac-key-staging"]) >= 32
    hmac1 = c.v["uid-hmac-key-staging"]
    r2 = run(c, {"ANTHROPIC_API_KEY": "sk-test-1"})
    assert r2.ok and len(c.adds) == 2 and c.v["uid-hmac-key-staging"] == hmac1


def test_changed_value_adds_version():
    c = Fake({"uid-hmac-key-staging": b"x" * 64, "anthropic-api-key": b"old"})
    run(c, {"ANTHROPIC_API_KEY": "new"})
    assert c.adds == ["anthropic-api-key"] and c.v["anthropic-api-key"] == b"new"


def test_missing_env_value():
    c = Fake()
    r = run(c, {})
    assert not r.ok  # no value and no existing version
    c2 = Fake({"anthropic-api-key": b"old", "uid-hmac-key-staging": b"h" * 64})
    assert run(c2, {}).ok and not c2.adds  # existing version kept


def test_admin_emails_only_when_requested():
    c = Fake()
    run(c, {"ANTHROPIC_API_KEY": "k", "ADMIN_ALLOWED_EMAILS": "a@x.com"})
    assert "admin-allowed-emails-staging" not in c.v
    run(c, {"ANTHROPIC_API_KEY": "k", "ADMIN_ALLOWED_EMAILS": "a@x.com"}, admin=True)
    assert c.v["admin-allowed-emails-staging"] == b"a@x.com"


def test_report_has_no_values():
    c = Fake()
    r = run(c, {"ANTHROPIC_API_KEY": "sk-secret-zzz"})
    assert "sk-secret-zzz" not in str(r.lines)
