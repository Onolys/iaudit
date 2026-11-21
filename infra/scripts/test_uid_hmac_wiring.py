"""Static check: services.tf wires UID_HMAC_KEY (secret ref uid-hmac-key-{env}) into api and worker."""
import pathlib
import re

TF = pathlib.Path(__file__).parent.parent / "modules" / "environment" / "services.tf"


def resource_block(text, name):
    m = re.search(r'resource "google_cloud_run_v2_service" "%s" \{' % name, text)
    assert m, name
    nxt = re.search(r'\nresource ', text[m.end():])
    return text[m.start(): m.end() + (nxt.start() if nxt else len(text))]


def test_api_and_worker_wire_uid_hmac_key():
    text = TF.read_text()
    for svc in ("api", "worker"):
        b = resource_block(text, svc)
        assert re.search(r'name\s*=\s*"UID_HMAC_KEY"\s*\n\s*value_source \{\s*secret_key_ref \{\s*secret\s*=\s*google_secret_manager_secret\.uid_hmac\.secret_id\s*version\s*=\s*"latest"', b), svc
