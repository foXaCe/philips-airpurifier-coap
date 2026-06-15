"""Tests for the system health information."""

from unittest.mock import MagicMock

from custom_components.philips_airpurifier_coap import system_health
from homeassistant.core import HomeAssistant

from .fixtures.mock_data import SAMPLE_STATUS_AC3033


async def test_system_health_register(hass: HomeAssistant) -> None:
    """async_register wires up the info callback."""
    register = MagicMock()
    system_health.async_register(hass, register)
    register.async_register_info.assert_called_once_with(system_health.system_health_info)


async def test_system_health_info(hass: HomeAssistant, setup_model) -> None:
    """The info reports the configured and connected device counts."""
    # No entries configured yet.
    assert await system_health.system_health_info(hass) == {
        "configured_devices": 0,
        "connected_devices": 0,
    }

    # A loaded, connected device is counted.
    await setup_model("AC3033", SAMPLE_STATUS_AC3033)
    info = await system_health.system_health_info(hass)
    assert info["configured_devices"] == 1
    assert info["connected_devices"] == 1
