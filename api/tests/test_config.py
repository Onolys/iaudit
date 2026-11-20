import pytest
from onolys_core.errors import ConfigError

from onolys_api.config import Settings

pytestmark = pytest.mark.unit


def test_defaults_local():
    s = Settings.from_env({})
    assert (s.env, s.service_mode, s.auth_mode, s.adapters) == ("local", "combined", "fake", "stub")
    assert s.daily_run_cap == 20 and s.firestore_database == "(default)"


def test_parses_all_vars():
    s = Settings.from_env(
        {
            "ENV": "staging",
            "SERVICE_MODE": "worker",
            "AUTH_MODE": "idp",
            "ADAPTERS": "real",
            "GCP_PROJECT": "p",
            "REGION": "r",
            "FIRESTORE_DATABASE": "staging",
            "AUTH_PROJECT": "ap",
            "AUDIO_BUCKET": "b",
            "CORS_ORIGINS": "https://a.com, https://b.com ,",
            "DAILY_RUN_CAP": "5",
            "TASKS_QUEUE": "q",
            "TASKS_SA": "sa",
            "WORKER_URL": "https://w",
            "ROUTES_FILE": "r.yaml",
            "DEFAULT_PRESET": "d",
            "GIT_SHA": "sha",
        }
    )
    assert s.service_mode == "worker" and s.firestore_database == "staging"
    assert s.cors_origins == ("https://a.com", "https://b.com") and s.daily_run_cap == 5
    assert s.git_sha == "sha" and s.worker_url == "https://w"


def test_non_local_defaults_are_api_idp_real():
    s = Settings.from_env({"ENV": "prod"})
    assert (s.service_mode, s.auth_mode, s.adapters) == ("api", "idp", "real")


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_fake_auth_rejected_outside_local(env):
    with pytest.raises(ConfigError, match="AUTH_MODE=fake"):
        Settings.from_env({"ENV": env, "AUTH_MODE": "fake"})


@pytest.mark.parametrize("env", ["local", "test"])
def test_fake_auth_allowed_locally(env):
    assert Settings.from_env({"ENV": env, "AUTH_MODE": "fake"}).auth_mode == "fake"


@pytest.mark.parametrize(
    "bad",
    [
        {"SERVICE_MODE": "x"},
        {"ENV": "dev"},
        {"ADAPTERS": "x"},
        {"AUTH_MODE": "x"},
        {"DAILY_RUN_CAP": "many"},
        {"DAILY_RUN_CAP": "-1"},
    ],
)
def test_invalid_values(bad):
    with pytest.raises(ConfigError):
        Settings.from_env(bad)
