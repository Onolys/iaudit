"""Tests for identity-config.py logic (fake client, no network). Run: python3 -m pytest infra/scripts -q"""
import importlib.util
import pathlib

spec = importlib.util.spec_from_file_location("identity_config", pathlib.Path(__file__).with_name("identity-config.py"))
ic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ic)


class Fake:
    def __init__(self, cfg):
        self.cfg = cfg
        self.patches = []

    def get(self):
        return self.cfg

    def patch(self, mask, body):
        self.patches.append((mask, body))


GOOD = {
    "passwordPolicyConfig": {
        "passwordPolicyEnforcementState": "ENFORCE",
        "passwordPolicyVersions": [{"customStrengthOptions": {"minPasswordLength": 8}}],
    },
    "emailPrivacyConfig": {"enableImprovedEmailPrivacy": True},
}


def test_patches_when_unset():
    c = Fake({})
    ic.ensure(c)
    mask, body = c.patches[0]
    assert set(mask.split(",")) == {"passwordPolicyConfig", "emailPrivacyConfig"}
    assert body["passwordPolicyConfig"]["passwordPolicyVersions"][0]["customStrengthOptions"]["minPasswordLength"] == 8
    assert body["emailPrivacyConfig"]["enableImprovedEmailPrivacy"] is True


def test_idempotent_when_already_set():
    c = Fake(GOOD)
    ic.ensure(c)
    assert c.patches == []


def test_add_domains_unions_and_skips_when_present():
    c = Fake({"authorizedDomains": ["localhost", "a.web.app"]})
    ic.add_domains(c, ["b.web.app", "a.web.app"])
    assert c.patches == [("authorizedDomains", {"authorizedDomains": ["localhost", "a.web.app", "b.web.app"]})]
    c2 = Fake({"authorizedDomains": ["a.web.app"]})
    ic.add_domains(c2, ["a.web.app"])
    assert c2.patches == []
