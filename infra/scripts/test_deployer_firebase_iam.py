"""Static check: deployers can read the Firebase project and run firebase-tools rules deploys.

Run 44809052492: `firebase deploy` failed with 403 on firebaserules `projects/onolys:test` (IAM names the bare project
resource by project NUMBER, not a ruleset) and "Failed to get Firebase project" (firebase.projects.get is project level, so the
conditional Hosting grant cannot cover it).
"""
import pathlib
import re

DEPLOYER = (pathlib.Path(__file__).parent.parent / "deployer.tf").read_text()


def block(kind, name):
    m = re.search(r'resource "%s" "%s" \{(.*?)\n\}' % (kind, name), DEPLOYER, re.S)
    assert m, name
    return m.group(1)


def test_custom_role_grants_only_firebase_project_get():
    b = block("google_project_iam_custom_role", "firebase_project_get")
    assert re.search(r'permissions\s*=\s*\["firebase\.projects\.get"\]', b)


def test_both_deployers_hold_firebase_project_get_unconditionally():
    for env in ("staging", "prod"):
        b = block("google_project_iam_member", f"deployer_{env}_firebase_project_get")
        assert "google_project_iam_custom_role.firebase_project_get.name" in b, env
        assert f"local.deployer_{env}_member" in b, env
        assert "condition" not in b, env


def test_rules_admin_is_project_level_without_name_condition():
    # IAM conditions on resource.name never matched firebaserules `projects/onolys:test` (403 in CI).
    for env in ("staging", "prod"):
        b = block("google_project_iam_member", f"deployer_{env}_rules_admin")
        assert '"roles/firebaserules.admin"' in b, env
        assert "condition" not in b, env
