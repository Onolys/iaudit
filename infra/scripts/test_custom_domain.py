"""Static checks on infra/domains.tf (custom domains + required_dns_updates output). Run: python3 -m pytest infra/scripts -q"""
import pathlib
import re

TF = pathlib.Path(__file__).parent.parent / "domains.tf"


def src():
    return TF.read_text()


def norm(b):
    return re.sub(r"[ \t]+=", " =", re.sub(r"=[ \t]+", "= ", b))


def block(text, header):
    m = re.search(re.escape(header) + r" \{", text)
    assert m, f"missing {header}"
    i, depth = m.end(), 1
    while depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.start():i]


def test_app_domain_on_prod_site_ungated():
    b = norm(block(src(), 'resource "google_firebase_hosting_custom_domain" "app"'))
    assert 'custom_domain = "app.onolys.com"' in b
    assert "google_firebase_hosting_site.app.site_id" in b
    assert "count" not in b  # always created
    assert "wait_dns_verification = false" in b  # owner adds DNS after apply


def test_admin_domain_gated_by_admin_enabled():
    b = norm(block(src(), 'resource "google_firebase_hosting_custom_domain" "admin"'))
    assert 'custom_domain = "admin.onolys.com"' in b
    assert "var.admin_enabled ? 1 : 0" in b
    assert "google_firebase_hosting_site.admin[0].site_id" in b


def test_no_staging_custom_domain():
    assert "staging.app.onolys.com" not in src()
    assert "google_firebase_hosting_custom_domain\" \"app_staging" not in src()


def test_required_dns_updates_output_shape():
    b = block(src(), 'output "required_dns_updates"')
    # flattened to {type, host, value} records, per domain
    for key in ("required_dns_updates", "desired", "records", "domain_name", "rdata", "type"):
        assert key in b
    assert "local.custom_domains" in b
    loc = block(src(), "locals")
    assert "google_firebase_hosting_custom_domain.app" in loc
    assert "google_firebase_hosting_custom_domain.admin" in loc
    assert "host" in b and "value" in b
    assert "verification" in b  # cert _acme-challenge TXT
