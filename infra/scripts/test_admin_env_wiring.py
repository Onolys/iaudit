"""Static check: the Cloud Run admin_backend service sets the env the admin gateway needs to start.

Regression: it set AUTH_PROJECT, but admin auth reads ADMIN_AUTH_PROJECT (or GCP_PROJECT), so the
container exited with ConfigError at startup and never listened on $PORT.
"""
import pathlib
import re

from onolys_admin_auth.config import AdminAuthConfig

TF = pathlib.Path(__file__).parent.parent / "modules" / "environment" / "services.tf"


def admin_block():
    text = TF.read_text()
    m = re.search(r'resource "google_cloud_run_v2_service" "admin_backend" \{', text)
    assert m
    nxt = re.search(r'\nresource ', text[m.end():])
    return text[m.start(): m.end() + (nxt.start() if nxt else len(text))]


def test_admin_service_env_satisfies_admin_auth_config():
    b = admin_block()
    env = {n: v for n, v in re.findall(r'env \{\s*name\s*=\s*"(\w+)"\s*value\s*=\s*([^\n]+)', b)}
    # Secret-backed vars: stand in a value, the secret ref itself is asserted below.
    secret_names = re.findall(r'env \{\s*name\s*=\s*"(\w+)"\s*value_source', b)
    assert "ADMIN_ALLOWED_EMAILS" in secret_names
    runtime = {k: "x" for k in env}
    runtime["ENV"] = "staging"
    runtime["ADMIN_AUTH"] = "on"
    runtime["ADMIN_ALLOWED_EMAILS"] = "a@example.com"
    for k in ("ADMIN_AUTH_PROJECT", "GCP_PROJECT"):
        if k in env:
            runtime[k] = "onolys"
    cfg = AdminAuthConfig.from_env(runtime)  # raises ConfigError if a required var is not wired
    assert cfg.enabled and cfg.project == "onolys"
