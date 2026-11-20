"""Sample tests proving the unit/integration/live marker convention (docs/reference/testing.md)."""

import pytest


@pytest.mark.unit
def test_unit_sample():
    assert True


@pytest.mark.integration
def test_integration_sample():
    assert True


@pytest.mark.live
def test_live_sample_is_excluded_by_default(pytestconfig):
    # Only runs with `-m live`; default addopts must deselect it otherwise.
    assert pytestconfig.getoption("markexpr") == "live"


def test_markers_registered_and_live_excluded_by_default(pytestconfig):
    registered = " ".join(pytestconfig.getini("markers"))
    for name in ("unit", "integration", "live"):
        assert f"{name}:" in registered
    assert "not live" in " ".join(pytestconfig.getini("addopts"))
