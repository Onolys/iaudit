"""Static check: provider-key secrets (llm_secrets/stt_secrets) are per environment, created and granted in the module."""
import pathlib
import re

INFRA = pathlib.Path(__file__).parent.parent
MOD = INFRA / "modules" / "environment"


def test_module_creates_env_suffixed_provider_secrets():
    text = (MOD / "secrets.tf").read_text()
    m = re.search(r'resource "google_secret_manager_secret" "provider" \{(.*?)\n\}', text, re.S)
    assert m, "module must create provider secret shells"
    assert 'secret_id = "${each.value}-${var.env}"' in m.group(1)


def test_root_no_longer_creates_shared_provider_secrets():
    text = (INFRA / "main.tf").read_text()
    assert 'resource "google_secret_manager_secret" "provider"' not in text
    assert "llm_secret_ids" not in text and "stt_secret_ids" not in text


def test_module_consumers_use_env_secret_not_raw_base_name():
    secrets = (MOD / "secrets.tf").read_text()
    services = (MOD / "services.tf").read_text()
    # IAM grants and env refs resolve the per-env shell, never the raw base name from the variable
    for needle in ("secret_id = each.value", "secret  = env.value"):
        assert needle not in secrets + services, needle
    assert "google_secret_manager_secret.provider[" in secrets
    assert "google_secret_manager_secret.provider[" in services


def test_legacy_shared_secret_dropped_from_state_not_deleted():
    text = (INFRA / "main.tf").read_text()
    assert re.search(r'removed \{\s*from\s*=\s*google_secret_manager_secret\.provider\s*lifecycle \{\s*destroy\s*=\s*false', text)
