"""Tests for LG soundbar model capability profiles."""

from homeassistant.components.lg_soundbar.models import capabilities_for_model


def test_sp11ra_has_wake_only_local_power() -> None:
    capabilities = capabilities_for_model("SP11RA")
    assert capabilities.local_power_on is True
    assert capabilities.local_power_off is False
    assert capabilities.power_state_from_connect is True


def test_dsp11ra_uses_same_power_profile() -> None:
    capabilities = capabilities_for_model("dsp11ra")
    assert capabilities.local_power_off is False
    assert capabilities.power_state_from_connect is True


def test_unknown_model_preserves_legacy_power_commands() -> None:
    capabilities = capabilities_for_model(None)
    assert capabilities.local_power_on is True
    assert capabilities.local_power_off is True
    assert capabilities.power_state_from_connect is False
