"""Static check: deployer-{env} may deploy the admin backend and admin hosting site, only when admin_enabled."""
import pathlib
import re

INFRA = pathlib.Path(__file__).parent.parent
DEPLOYER = (INFRA / "deployer.tf").read_text()
OUTPUTS = (INFRA / "modules" / "environment" / "outputs.tf").read_text()


def local_block(name):
    m = re.search(r"^\s*%s\s*=\s*" % re.escape(name), DEPLOYER, re.M)
    assert m, name
    return DEPLOYER[m.start(): m.start() + 600]


def test_module_exposes_admin_outputs_null_when_disabled():
    for out in ("admin_backend_service_name", "admin_backend_sa_email"):
        m = re.search(r'output "%s" \{(.*?)\n\}' % out, OUTPUTS, re.S)
        assert m, out
        assert "one(" in m.group(1), f"{out} must be null when admin is disabled"


def test_cloud_run_developer_includes_admin_only_when_enabled():
    for env in ("staging", "prod"):
        b = local_block(f"{env}_services")
        assert f"module.{env}.admin_backend_service_name" in b, env
        assert "var.admin_enabled" in b, env


def test_runtime_sa_user_includes_admin_sa_only_when_enabled():
    for env in ("staging", "prod"):
        m = re.search(r'resource "google_service_account_iam_member" "deployer_%s_runtime_user" \{(.*?)\n\}' % env, DEPLOYER, re.S)
        assert m, env
        assert f"local.{env}_runtime_sas" in m.group(1), env
        assert "var.admin_enabled" in DEPLOYER[DEPLOYER.index(f"{env}_runtime_sas") :][:400], env


def test_hosting_admin_is_project_level_without_name_condition():
    # Run 44812626576: 403 on firebasehosting `.../sites/onolys-app-staging/versions` with a resource.name condition.
    # Hosting site resources are unknown to Policy Troubleshooter and never matched the condition (covers admin sites too).
    for env in ("staging", "prod"):
        m = re.search(r'resource "google_project_iam_member" "deployer_%s_hosting" \{(.*?)\n\}' % env, DEPLOYER, re.S)
        assert m, env
        assert '"roles/firebasehosting.admin"' in m.group(1), env
        assert "condition" not in m.group(1), env
    assert "hosting_staging_sites" not in DEPLOYER and "hosting_prod_sites" not in DEPLOYER
